"""GUIとCLIで共通の実行手順。ログ保存はRunLog、後片付けはExitStackへ。"""

import logging
from contextlib import ExitStack

from src.agent import HelpDeskAgent
from src.llm import LLM
from src.security import endpoint, validate_question
from workshop.checks import fetch_models, preflight, require_loaded_model
from workshop.run_log import RunLog
from workshop.runner_lock import single_run
from workshop.search import ROOT, LocalSearch, build_index

DEFAULT_QUESTION = "過去のQAを参照して、二段階認証で認証アプリを使う設定手順を教えてください。"


def list_models(settings, timeout=10):
    _base, remote = endpoint(settings.openai_api_base)
    models = fetch_models(settings.openai_api_base, timeout=timeout)
    if remote:
        return [model for model in models if model["id"].endswith(":free")]
    return [model for model in models if model.get("type") in {"llm", "vlm", "embeddings"}]


def prepare_index(settings):
    with single_run():
        return dict(build_index(settings))


def execute(settings, command, question=DEFAULT_QUESTION):
    with single_run():
        return _execute(settings, command, question)


def _execute(settings, command, question):
    if command == "run":
        validate_question(question)
    local_model = require_loaded_model(settings)
    with RunLog(ROOT, settings, command, local_model) as record, ExitStack() as resources:
        llm = search = None
        try:
            if local_model:
                logging.info("LM Studio context_length=%s (GUI設定)", local_model["loaded_context_length"])
            if command == "preflight":
                llm = LLM(settings)
                resources.callback(llm.close)
                result = preflight(llm)
                success = all(check["ok"] for check in result["checks"].values())
            elif command == "run":
                record.record_question(question)
                search = LocalSearch(settings)
                resources.callback(search.close)
                agent = HelpDeskAgent(settings, tools=search.tools())
                llm = agent.llm
                resources.callback(llm.close)
                result = agent.run_agent(question).model_dump()
                success = all(item["is_completed"] for item in result["subtasks"])
                result["all_subtasks_completed"] = success
            else:
                raise ValueError("実行コマンドはrunかpreflightです")
            result["status"] = "passed" if success else "incomplete"
        except Exception as exc:
            result = record.failure(exc, question if command == "run" else None)
        result["api_calls"] = llm.calls if llm else 0
        result["embedding_query_calls"] = search.query_calls if search else 0
        return record.save(result)
