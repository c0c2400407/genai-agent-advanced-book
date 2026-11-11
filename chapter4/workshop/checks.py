"""LM Studioの言語モデル状態を確認し、質問実行時は選択モデルへ切り替える。"""

import json
import logging
import time

import httpx

from src.models import Plan
from src.security import endpoint, http_client, public_error, reveal

logger = logging.getLogger(__name__)


def fetch_models(base_url, timeout=10, local_only=False, api_key=None):
    base, remote = endpoint(base_url, local_only=local_only)
    url = base + "/models" if remote else base.removesuffix("/v1") + "/api/v0/models"
    provider = "OpenRouter" if remote else "LM Studio"
    key = reveal(api_key)
    if remote and not key:
        raise ValueError("OpenRouter APIキーを入力してください")
    logger.info("MODEL_LIST_REQUEST provider=%s status=started", provider)
    try:
        with http_client(timeout=timeout) as client:
            headers = {"Authorization": f"Bearer {key}"} if remote else None
            response = client.get(url, headers=headers)
            logger.info("MODEL_LIST_RESPONSE provider=%s http_status=%d", provider, response.status_code)
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
        logger.info("MODEL_LIST_REQUEST provider=%s status=success count=%d", provider, len(models))
        return models
    except Exception as exc:
        chain = []
        current = exc
        seen = set()
        while current is not None and id(current) not in seen and len(chain) < 5:
            seen.add(id(current))
            chain.append(type(current).__name__)
            current = current.__cause__ or current.__context__
        response = getattr(exc, "response", None)
        http_status = getattr(response, "status_code", None)
        logger.error(
            "MODEL_LIST_REQUEST provider=%s status=failed exception_chain=%s http_status=%s",
            provider,
            ">".join(chain),
            http_status if http_status is not None else "none",
        )
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


def _load_selected_lmstudio_model(base_url, model_id, api_key):
    api_url = base_url.removesuffix("/v1") + "/api/v1"
    key = reveal(api_key)
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    started = time.monotonic()
    logger.info("MODEL_AUTO_LOAD status=started model=%s", model_id)
    try:
        with http_client(timeout=600) as client:
            response = client.get(api_url + "/models", headers=headers)
            logger.info("MODEL_MANAGER_LIST http_status=%d", response.status_code)
            response.raise_for_status()
            catalogue = response.json().get("models")
            if not isinstance(catalogue, list):
                raise ValueError("LM Studioモデル管理APIの一覧形式が不正です")
            selected = next(
                (
                    item
                    for item in catalogue
                    if isinstance(item, dict) and item.get("key") == model_id and item.get("type") == "llm"
                ),
                None,
            )
            if selected is None:
                raise ValueError(
                    f"指定した言語モデル {model_id!r} がLM Studioにありません。モデルをダウンロードして一覧を更新してください。"
                )
            instances = selected.get("loaded_instances", [])
            if not isinstance(instances, list):
                raise ValueError("LM Studioモデルのロード状態が不正です")

            if not instances:
                response = client.post(api_url + "/models/load", headers=headers, json={"model": model_id})
                logger.info("MODEL_AUTO_LOAD_RESPONSE http_status=%d", response.status_code)
                response.raise_for_status()
                loaded = response.json()
                if not isinstance(loaded, dict) or loaded.get("status") != "loaded":
                    raise ValueError("LM Studioからモデルロード完了を確認できませんでした")
                logger.info(
                    "MODEL_AUTO_LOAD status=success model=%s seconds=%.2f",
                    model_id,
                    time.monotonic() - started,
                )
            else:
                logger.info("MODEL_AUTO_LOAD status=already_loaded model=%s", model_id)

            # Keep the existing one-chat-model memory policy when switching models.
            for item in catalogue:
                if not isinstance(item, dict) or item.get("type") != "llm" or item.get("key") == model_id:
                    continue
                old_instances = item.get("loaded_instances", [])
                if not isinstance(old_instances, list):
                    continue
                for instance in old_instances:
                    instance_id = instance.get("id") if isinstance(instance, dict) else None
                    if not isinstance(instance_id, str) or not instance_id:
                        continue
                    response = client.post(
                        api_url + "/models/unload", headers=headers, json={"instance_id": instance_id}
                    )
                    logger.info("MODEL_AUTO_UNLOAD model=%s http_status=%d", item.get("key"), response.status_code)
                    response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        logger.error("MODEL_AUTO_LOAD status=failed http_status=%d", status)
        if status in {404, 405}:
            raise RuntimeError("このLM Studioは自動ロードAPIに対応していません。LM Studio 0.4.0以降へ更新してください。") from None
        if status in {401, 403}:
            raise RuntimeError("LM Studio APIの認証に失敗しました。APIトークンの設定を確認してください。") from None
        raise RuntimeError(f"LM Studioのモデル管理APIがHTTP {status}を返しました。") from None
    except Exception as exc:
        logger.error("MODEL_AUTO_LOAD status=failed exception_chain=%s", type(exc).__name__)
        if isinstance(exc, (ValueError, RuntimeError)):
            raise
        raise RuntimeError(public_error(exc)) from None


def require_loaded_model(settings, *, auto_load=False):
    base, remote = endpoint(settings.openai_api_base)
    if remote:
        return
    available = fetch_models(settings.openai_api_base, local_only=True)
    models = [model for model in available if model.get("state") == "loaded" and model.get("type") in {"llm", "vlm"}]
    loaded = [model["id"] for model in models]
    if auto_load:
        selected = next(
            (model for model in available if model["id"] == settings.openai_model and model.get("type") in {"llm", "vlm"}),
            None,
        )
        if selected is None:
            raise ValueError(
                f"指定した言語モデル {settings.openai_model!r} がLM Studioにありません。モデルをダウンロードして一覧を更新してください。"
            )
        if loaded != [settings.openai_model]:
            _load_selected_lmstudio_model(base, settings.openai_model, settings.openai_api_key)
            models = [
                model
                for model in fetch_models(settings.openai_api_base, local_only=True)
                if model.get("state") == "loaded" and model.get("type") in {"llm", "vlm"}
            ]
            loaded = [model["id"] for model in models]
    if loaded != [settings.openai_model]:
        if auto_load:
            raise ValueError(
                f"LM Studioで指定モデル {settings.openai_model!r} のロード完了を確認できませんでした。モデル一覧を更新してください。"
            )
        raise ValueError(
            "LM Studioは使用する言語モデル1つだけを事前ロードしてください。"
            f" 指定={settings.openai_model!r}, ロード済み={loaded!r}。"
            "別モデルの自動ロードを避けるため実行を停止しました。"
        )
    return {key: models[0].get(key) for key in ["id", "state", "loaded_context_length", "max_context_length"]}


def capability_problem(model, tool_mode, structured_mode, require_native=False):
    """公開メタデータと設定の不整合を説明する。設定は自動変更しない。"""
    parameters = model.get("supported_parameters")
    if not isinstance(parameters, list) or not all(isinstance(item, str) for item in parameters):
        return "対応機能を確認できません。モデル一覧を更新するか、別の無料モデルを選んでください。"
    if structured_mode == "schema" and not {"response_format", "structured_outputs"}.issubset(parameters):
        return "このモデルはschema構造化出力への対応が公開一覧にありません。「構造化出力」をjsonへ変更するか、schema対応モデルを選んでください。"
    if (tool_mode == "native" or require_native) and not {"tools", "tool_choice"}.issubset(parameters):
        return "このモデルはネイティブツール呼び出しへの対応が公開一覧にありません。" + (
            "接続・機能確認にはネイティブツール対応モデルを選んでください。"
            if require_native
            else "「ツール」をjsonへ変更するか、ツール対応モデルを選んでください。"
        )
    return ""


def require_remote_capabilities(settings, require_native=False):
    _base, remote = endpoint(settings.openai_api_base)
    if not remote:
        return
    if not settings.openai_model.endswith(":free"):
        raise ValueError("OpenRouterでは末尾:freeの固定モデルを選んでください")
    selected = next(
        (
            model
            for model in fetch_models(settings.openai_api_base, api_key=settings.openai_api_key)
            if model["id"] == settings.openai_model
        ),
        None,
    )
    if selected is None:
        raise ValueError("選択したモデルが公開一覧にありません。モデル一覧を更新して選び直してください。")
    problem = capability_problem(selected, settings.tool_mode, settings.structured_mode, require_native)
    if problem:
        raise ValueError(problem)


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
