"""OpenRouter / LM Studio共通の呼び出し。自動の追加API再試行はしない。"""
import json
import logging
import time

from openai import OpenAI
from src.security import endpoint, http_client, public_error, reveal

logger = logging.getLogger(__name__)


class LLM:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.model = settings.openai_model
        base_url, self.remote = endpoint(settings.openai_api_base)
        key = reveal(settings.openai_api_key)
        if not settings.openai_model:
            raise ValueError("LLM_MODELにモデルIDを明示してください")
        if self.remote:
            if not key or key.startswith("<"):
                raise ValueError("chapter4/.envにLLM_API_KEYを設定してください")
            if not settings.openai_model.endswith(":free"):
                raise ValueError("勉強会版のOpenRouterは固定の:freeモデルIDのみ使用できます")
        if settings.structured_mode not in {"schema", "json"} or settings.tool_mode not in {"native", "json"}:
            raise ValueError("STRUCTURED_MODE=schema/json、TOOL_MODE=native/jsonを指定してください")
        self.client = client or OpenAI(
            base_url=base_url,
            api_key=(key if key and not key.startswith("sk-or-") else "lm-studio") if not self.remote else key,
            timeout=180.0, max_retries=0,
            http_client=http_client(),
        )
        self.calls = 0
        self.last_request = 0.0

    def complete(self, **kwargs):
        if self.calls >= self.settings.max_api_calls:
            raise RuntimeError("MAX_API_CALLSに達したため停止しました")
        if kwargs.get("model") != self.model:
            raise ValueError("設定したモデル以外への切り替えは許可されていません")
        if self.remote:
            time.sleep(max(0, self.settings.request_interval - (time.monotonic() - self.last_request)))
            kwargs["extra_body"] = {"provider": {"require_parameters": True,
                "max_price": {"prompt": 0, "completion": 0, "request": 0}}}
        if self.settings.reasoning_effort:
            kwargs.setdefault("reasoning_effort", self.settings.reasoning_effort)
        elif not self.remote:
            kwargs.setdefault("reasoning_effort", "none")
        self.calls += 1
        self.last_request = time.monotonic()
        kwargs.pop("seed", None)
        kwargs.setdefault("max_tokens", self.settings.max_output_tokens)
        logger.info("API call %d/%d model=%s", self.calls, self.settings.max_api_calls, self.settings.openai_model)
        started = time.monotonic()
        try:
            response = self.client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise RuntimeError(public_error(exc, [self.settings.openai_api_key])) from None
        if not response.choices:
            raise ValueError("API応答にchoicesがありません")
        if response.choices[0].finish_reason == "length":
            raise ValueError("出力がトークン上限で打ち切られました。思考モードとMAX_OUTPUT_TOKENSを確認してください")
        logger.info("API response model=%s seconds=%.2f tokens=%s", response.model,
                    time.monotonic() - started, response.usage.total_tokens if response.usage else None)
        return response

    def close(self):
        self.client.close()

    def structured(self, schema, *, messages, **kwargs):
        messages = list(messages)
        definition = schema.model_json_schema()
        if schema.__name__ == "Plan":
            definition["properties"]["subtasks"].update(minItems=1, maxItems=self.settings.max_subtasks)
        if self.settings.structured_mode == "schema":
            definition["additionalProperties"] = False
            kwargs["response_format"] = {"type": "json_schema", "json_schema": {
                "name": schema.__name__, "strict": True, "schema": definition,
            }}
        else:
            messages.append({"role": "user", "content": "次のJSON Schemaに従うJSONオブジェクトのみを返してください。説明やコードフェンスは不要です。\n" + json.dumps(definition, ensure_ascii=False)})
        response = self.complete(messages=messages, **kwargs)
        content = response.choices[0].message.content
        if not content:
            raise ValueError("構造化出力が空です")
        return schema.model_validate_json(content)
