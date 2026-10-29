"""1回の実行に対応するログ・メタデータ・結果JSONの保存。"""

import json
import logging
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.security import RedactingFormatter, public_error, redact_payload, safe_dir


class RunLog:
    def __init__(self, root, settings, command, local_model):
        self.settings = settings
        self.secrets = [settings.openai_api_key, settings.embedding_api_key]
        folder = safe_dir(root / "workshop" / "logs", root)
        stem = datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-" + command
        self.path = folder / (stem + ".json")
        self.log_path = folder / (stem + ".log")
        self.started = time.monotonic()
        self.metadata = {
            "model": settings.openai_model,
            "base_url": settings.openai_api_base,
            "tool_mode": settings.tool_mode,
            "structured_mode": settings.structured_mode,
            "started_at": datetime.now(timezone(timedelta(hours=9))).isoformat(),
            "local_model": local_model,
            "max_output_tokens": settings.max_output_tokens,
            "max_subtasks": settings.max_subtasks,
            "max_challenges": settings.max_challenges,
            "search_backend": settings.search_backend,
            "embedding_model": settings.embedding_model if settings.search_backend == "lmstudio" else None,
        }

    def __enter__(self):
        self.handler = logging.FileHandler(self.log_path, mode="x", encoding="utf-8")
        self.handler.setLevel(logging.INFO)
        self.handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(message)s", self.secrets))
        root = logging.getLogger()
        self.previous_level = root.level
        root.setLevel(min(root.level, logging.INFO))
        root.addHandler(self.handler)
        return self

    def __exit__(self, *_exc):
        root = logging.getLogger()
        root.removeHandler(self.handler)
        self.handler.close()
        root.setLevel(self.previous_level)

    def record_question(self, question):
        if self.settings.save_full_logs:
            logging.info("QUESTION %s", json.dumps(redact_payload(question, self.secrets), ensure_ascii=False))

    def failure(self, exc, question=None):
        result = {
            "status": "error",
            "error": public_error(exc, self.secrets),
            "error_type": type(exc).__name__,
            "error_location": [
                f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
                for frame in traceback.extract_tb(exc.__traceback__)
            ],
        }
        if question is not None and self.settings.save_full_logs:
            result["question"] = question
        logging.error("実行失敗: %s", result["error"])
        logging.error("ERROR_LOCATION %s %s", result["error_type"], result["error_location"])
        return result

    def save(self, result):
        result = redact_payload(
            {**self.metadata, **result, "elapsed_seconds": round(time.monotonic() - self.started, 2)}, self.secrets
        )
        diagnostic_fields = self.metadata.keys() | {
            "status",
            "error",
            "error_type",
            "error_location",
            "api_calls",
            "embedding_query_calls",
            "elapsed_seconds",
            "all_subtasks_completed",
        }
        record = (
            dict(result)
            if self.settings.save_full_logs
            else {key: value for key, value in result.items() if key in diagnostic_fields}
        )
        record["content_saved"] = self.settings.save_full_logs
        with self.path.open("x", encoding="utf-8") as output:
            json.dump(record, output, ensure_ascii=False, indent=2)
        return result, self.path
