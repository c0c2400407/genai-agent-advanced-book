import argparse
import json
import logging
import sys
from src.security import ensure_runtime, public_error

from src.configs import Settings
from src.custom_logger import configure_logging
from workshop.checks import require_loaded_model
from workshop.search import LocalSearch, build_index
from workshop.service import DEFAULT_QUESTION, execute, list_models, prepare_index


def main():
    ensure_runtime()
    configure_logging()
    for stream in [sys.stdout, sys.stderr]:
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="第4章 ヘルプデスク勉強会版")
    parser.add_argument("command", choices=["gui", "models", "status", "index", "search", "preflight", "run"])
    parser.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    parser.add_argument("--base-url")
    parser.add_argument("--model")
    parser.add_argument("--tool-mode", choices=["native", "json"])
    parser.add_argument("--structured-mode", choices=["schema", "json"])
    args = parser.parse_args()
    if args.command == "gui":
        from workshop.gui import launch

        launch()
        return 0
    if args.command == "index":
        print(json.dumps(prepare_index(Settings()), ensure_ascii=False))
        return 0
    if args.command == "search":
        search = LocalSearch(Settings())
        try:
            for kind in ["manual", "qa"]:
                print(
                    kind,
                    json.dumps(
                        [hit.model_dump() for hit in search.search(args.question, kind)], ensure_ascii=False, indent=2
                    ),
                )
        finally:
            search.close()
        return 0
    settings = Settings()
    for arg, field in [
        (args.base_url, "openai_api_base"),
        (args.model, "openai_model"),
        (args.tool_mode, "tool_mode"),
        (args.structured_mode, "structured_mode"),
    ]:
        if arg:
            setattr(settings, field, arg)
    if args.command == "models":
        for model in list_models(settings):
            print(
                model["id"],
                "type=",
                model.get("type"),
                "state=",
                model.get("state"),
                "context=",
                model.get("loaded_context_length"),
                "supported_parameters=",
                ",".join(model.get("supported_parameters", [])),
            )
        return 0
    if args.command == "status":
        current = require_loaded_model(settings)
        print(
            json.dumps(
                {
                    "model": settings.openai_model,
                    "base_url": settings.openai_api_base,
                    "local_model": current,
                    "max_output_tokens": settings.max_output_tokens,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    result, path = execute(settings, args.command, args.question)
    print(result.get("answer", result.get("error", "")))
    print(f"結果: {path}")
    return {"passed": 0, "incomplete": 2, "error": 1}[result["status"]]


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"停止: {public_error(exc)}", file=sys.stderr)
        sys.exit(1)
