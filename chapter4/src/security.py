"""通信・秘密情報・入力サイズの境界。モデル出力を命令として実行しない。"""

import json
import logging
import re
import sys
import ssl
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from openai import APIConnectionError, APIStatusError
from pydantic import SecretStr, ValidationError

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_QUESTION_CHARS = 4000
MAX_QUERY_CHARS = 256
MAX_TOOL_CALLS = 2


def ensure_runtime():
    if not (3, 14, 10) <= sys.version_info[:3] < (3, 15, 0):
        raise RuntimeError(
            "対策版はPython 3.14.10以上の3.14系で起動してください。導入ガイドに従って仮想環境を作り直してください。名前は.venvやvenvで構いません。"
        )
    if ssl.OPENSSL_VERSION_INFO < (3, 5, 0, 9, 0):
        raise RuntimeError("OpenSSLのセキュリティ更新を含むPython配布物が必要です")


def reveal(value):
    return value.get_secret_value() if isinstance(value, SecretStr) else str(value or "")


def endpoint(value, *, local_only=False):
    if not isinstance(value, str) or len(value) > 256 or any(ord(c) < 33 for c in value):
        raise ValueError("接続先URLの形式が不正です")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError("接続先URLの形式が不正です") from None
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise ValueError("接続先URLにユーザー情報・クエリ・フラグメントは指定できません")
    if parsed.hostname == "openrouter.ai" and not local_only:
        if parsed.scheme != "https" or port not in {None, 443} or parsed.path.rstrip("/") != "/api/v1":
            raise ValueError("OpenRouterの接続先は https://openrouter.ai/api/v1 を指定してください")
        return "https://openrouter.ai/api/v1", True
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.scheme not in {"http", "https"}:
        raise ValueError("接続先は公式OpenRouterまたはローカルのLM Studioに限定されています")
    if parsed.path.rstrip("/") != "/v1" or port == 0:
        raise ValueError("LM Studioの接続先は http://localhost:1234/v1 形式で指定してください")
    host = "[::1]" if parsed.hostname == "::1" else "127.0.0.1"
    return f"{parsed.scheme}://{host}" + (f":{port}" if port is not None else "") + "/v1", False


class BoundedStream(httpx.SyncByteStream):
    def __init__(self, stream, limit):
        self.stream, self.limit = stream, limit

    def __iter__(self):
        size = 0
        for chunk in self.stream:
            size += len(chunk)
            if size > self.limit:
                self.stream.close()
                raise httpx.ReadError("API応答のサイズ上限を超えました")
            yield chunk

    def close(self):
        self.stream.close()


class BoundedTransport(httpx.BaseTransport):
    def __init__(self, transport=None, limit=MAX_RESPONSE_BYTES):
        self.transport = transport or httpx.HTTPTransport(trust_env=False, retries=0)
        self.limit = limit

    def handle_request(self, request):
        response = self.transport.handle_request(request)
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            response.close()
            raise httpx.ReadError("圧縮されたAPI応答は受け付けません")
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            stream=BoundedStream(response.stream, self.limit),
            extensions=response.extensions,
        )

    def close(self):
        self.transport.close()


def http_client(timeout=180):
    # ローカル宛ての質問やキーを、環境変数の外部プロキシへ送らない。
    return httpx.Client(
        transport=BoundedTransport(),
        trust_env=False,
        follow_redirects=False,
        timeout=timeout,
        headers={"Accept-Encoding": "identity"},
    )


def public_error(exc, secrets=()):
    if isinstance(exc, (APIStatusError, httpx.HTTPStatusError)):
        code = exc.status_code if isinstance(exc, APIStatusError) else exc.response.status_code
        # 本文は表示せず、404の既知の理由だけを定型文へ変換する。
        if code == 404:
            try:
                body = exc.response.json()
                message = body.get("error", {}).get("message", "")
                message = message.lower() if isinstance(message, str) else ""
            except (ValueError, AttributeError, TypeError):
                message = ""
            if "data policy" in message or "privacy" in message:
                return "APIがHTTP 404を返しました。OpenRouterのプライバシー設定と利用可能な配信先が一致していません。設定内容と配信先の利用条件を確認してください。"
            if "parameter" in message or "tool use" in message:
                return "APIがHTTP 404を返しました。指定した構造化出力・ツール等に対応する配信先がありません。モデルの対応機能と設定を確認してください。"
            return "APIがHTTP 404を返しました。モデルID、配信先の稼働状況、対応機能、OpenRouterのプライバシー設定を確認してください。"
        return f"APIがHTTP {code}を返しました。接続先、認証、モデル、利用制限を確認してください。"
    if isinstance(exc, (APIConnectionError, httpx.HTTPError)):
        return "APIとの通信に失敗しました。接続先とサーバーの状態を確認してください。"
    if isinstance(exc, ValidationError):
        return "設定またはモデル応答の形式・サイズが不正です。設定値とモデルの対応機能を確認してください。"
    return redact(str(exc), secrets)[:1000]


def redact(text, secrets=()):
    text = str(text)
    for value in secrets:
        value = reveal(value)
        if len(value) >= 6 and value not in {"lm-studio"}:
            text = text.replace(value, "[REDACTED]")
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}", "[REDACTED]", text)
    text = re.sub(r"(?i)\bBearer\s+[^\s\"']+", "Bearer [REDACTED]", text)
    return text


def redact_payload(value, secrets=()):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if "apikey" in key.lower().replace("_", "").replace("-", "") or key.lower() == "authorization"
            else redact_payload(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_payload(item, secrets) for item in value]
    if isinstance(value, str):
        return redact(value, secrets)
    return value


class RedactingFormatter(logging.Formatter):
    def __init__(self, fmt, secrets=(), **kwargs):
        super().__init__(fmt, **kwargs)
        self.secrets = secrets

    def format(self, record):
        return redact(super().format(record), self.secrets)


def validate_question(question):
    if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION_CHARS:
        raise ValueError(f"質問は1〜{MAX_QUESTION_CHARS}文字で入力してください")
    return question


def query_arguments(raw, expected):
    if not isinstance(raw, str) or len(raw) > 2048:
        raise ValueError("検索ツールの引数が不正です")

    def pairs(items):
        data = {}
        for key, value in items:
            if key in data:
                raise ValueError("検索引数のキーが重複しています")
            data[key] = value
        return data

    try:
        args = json.loads(raw, object_pairs_hook=pairs)
    except (json.JSONDecodeError, RecursionError):
        raise ValueError("検索ツールの引数はJSONオブジェクトで指定してください") from None
    if not isinstance(args, dict) or set(args) != set(expected):
        raise ValueError("検索ツールの引数名が不正です")
    if any(
        not isinstance(value, str)
        or not value.strip()
        or len(value) > MAX_QUERY_CHARS
        or any(ord(c) < 32 and c not in "\t\n\r" for c in value)
        for value in args.values()
    ):
        raise ValueError(f"検索語は1〜{MAX_QUERY_CHARS}文字の文字列で指定してください")
    return args


def read_json(path, max_bytes):
    path = Path(path)
    if path.is_symlink() or path.is_junction() or not path.is_file() or path.stat().st_size > max_bytes:
        raise ValueError("検索キャッシュのファイル形式またはサイズが不正です。作成し直してください")
    with path.open("rb") as source:
        content = source.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError("検索キャッシュがサイズ上限を超えています")
    try:
        return json.loads(content)
    except (ValueError, RecursionError):
        raise ValueError("検索キャッシュのJSONが不正です。作成し直してください") from None


def safe_dir(path, root):
    root, path = Path(root).resolve(), Path(path).absolute()
    if not path.resolve().is_relative_to(root) or ".." in path.parts:
        raise ValueError("作業フォルダ外への書き込みを拒否しました")
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink() or current.is_junction():
            raise ValueError("作業用フォルダのリンク・ジャンクションは使用できません")
        current.mkdir(exist_ok=True)
    return path


def write_json_atomic(path, value, root):
    path = Path(path)
    safe_dir(path.parent, root)
    descriptor, temporary = tempfile.mkstemp(prefix=".index-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
