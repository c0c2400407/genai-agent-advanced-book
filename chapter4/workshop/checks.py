"""LM Studioの意図しない別モデル自動ロードを防ぐ。"""

import json
import logging

from src.models import Plan
from src.security import endpoint, http_client, public_error


def fetch_models(base_url, timeout=10, local_only=False):
    base, remote = endpoint(base_url, local_only=local_only)
    url = base + "/models" if remote else base.removesuffix("/v1") + "/api/v0/models"
    try:
        with http_client(timeout=timeout) as client:
            response = client.get(url)
            response.raise_for_status()
            models = response.json()["data"]
        if (
            not isinstance(models, list)
            or len(models) > 5000
            or any(
                not isinstance(model, dict)
                or not isinstance(model.get("id"), str)
                or not 1 <= len(model["id"]) <= 256
                or any(ord(c) < 32 for c in model["id"])
                for model in models
            )
        ):
            raise ValueError("モデル一覧の形式またはサイズが不正です")
        return models
    except Exception as exc:
        raise RuntimeError(public_error(exc)) from None


def require_embedding_model(settings):
    endpoint(settings.embedding_base_url, local_only=True)
    if not settings.embedding_model:
        raise ValueError("検索に使用するEmbeddingモデルを選択してください")
    selected = [
        model
        for model in fetch_models(settings.embedding_base_url, local_only=True)
        if model["id"] == settings.embedding_model
        and model.get("type") == "embeddings"
        and model.get("state") == "loaded"
    ]
    if len(selected) != 1:
        raise ValueError(
            f"Embeddingモデル {settings.embedding_model!r} をLM StudioのGUIでロードしてから実行してください"
        )
    return selected[0]


def require_loaded_model(settings):
    _base, remote = endpoint(settings.openai_api_base)
    if remote:
        return
    models = [
        model
        for model in fetch_models(settings.openai_api_base, local_only=True)
        if model.get("state") == "loaded" and model.get("type") in {"llm", "vlm"}
    ]
    loaded = [model["id"] for model in models]
    if loaded != [settings.openai_model]:
        raise ValueError(
            "LM Studioは使用する言語モデル1つだけを事前ロードしてください。"
            f" 指定={settings.openai_model!r}, ロード済み={loaded!r}。"
            "別モデルの自動ロードを避けるため実行を停止しました。"
        )
    return {key: models[0].get(key) for key in ["id", "state", "loaded_context_length", "max_context_length"]}


def preflight(llm):
    """3リクエストで接続、ネイティブツール、構造化出力を別々に確認する。"""
    model = llm.settings.openai_model
    report = {
        "model": model,
        "base_url": llm.settings.openai_api_base,
        "structured_mode": llm.settings.structured_mode,
        "checks": {},
    }
    tests = [
        (
            "connection",
            lambda: llm.complete(model=model, messages=[{"role": "user", "content": "Reply OK."}], max_tokens=64),
        ),
        (
            "native_tool",
            lambda: llm.complete(
                model=model,
                messages=[{"role": "user", "content": "Call lookup with query パスワード."}],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "description": "Search a manual",
                            "parameters": {
                                "type": "object",
                                "properties": {"query": {"type": "string"}},
                                "required": ["query"],
                                "additionalProperties": False,
                            },
                        },
                    }
                ],
                tool_choice="required",
                max_tokens=256,
            ),
        ),
        (
            "structured_output",
            lambda: llm.structured(
                Plan,
                model=model,
                messages=[
                    {"role": "user", "content": "パスワード変更手順を調べるサブタスクを1件だけ作成してください。"}
                ],
                max_tokens=512,
            ),
        ),
    ]
    for name, operation in tests:
        try:
            response = operation()
            if name == "native_tool":
                calls = response.choices[0].message.tool_calls
                assert calls and calls[0].function.name == "lookup", "native tool_callsがありません"
                args = json.loads(calls[0].function.arguments)
                assert isinstance(args.get("query"), str) and args["query"], "ツール引数が不正です"
                value = {"tool": calls[0].function.name, "arguments": args}
            elif name == "structured_output":
                assert len(response.subtasks) == 1, "サブタスク数が1件ではありません"
                value = response.model_dump()
            else:
                value = response.choices[0].message.content
                assert value and value.strip(), "応答が空です"
            report["checks"][name] = {"ok": True, "output": value}
        except Exception as exc:
            report["checks"][name] = {"ok": False, "error": str(exc)}
        logging.info("%s %s", name, "PASS" if report["checks"][name]["ok"] else "FAIL")
    return report
