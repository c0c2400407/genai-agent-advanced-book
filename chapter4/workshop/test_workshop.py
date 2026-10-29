"""外部APIを使わず、実グラフとHTTP境界を確認する回帰テスト。"""

import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import httpx
from openai import OpenAI

from src.agent import HelpDeskAgent
from src.configs import Settings
from src.llm import LLM
from src.models import Plan
from workshop.search import LocalSearch, build_index
from workshop.checks import require_loaded_model
from workshop.runner_lock import single_run
from workshop.service import execute


class WorkshopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build_index()

    def settings(self, **overrides):
        return Settings(
            _env_file=None,
            openai_api_base="http://localhost:1234/v1",
            openai_model="test-local",
            request_interval=0,
            **overrides,
        )

    def test_search_real_qa(self):
        hits = LocalSearch().search("二段階認証 認証アプリ", "qa")
        self.assertIn("QRコード", hits[0].content)
        self.assertEqual(LocalSearch().search("", "qa"), [])

    def test_remote_paid_or_unspecified_model_rejected(self):
        for model in ["", "openrouter/free", "vendor/paid-model"]:
            with self.assertRaises(ValueError):
                LLM(Settings(_env_file=None, openai_api_key="fake", openai_model=model))

    def run_flow(self, tool_mode, completed_on_retry=True):
        payloads = []
        answers = [
            {"subtasks": ["認証アプリの設定手順を調べる"]},
            "tool",
            "情報が不足しています。",
            {"advice": "二段階認証と認証アプリで再検索", "is_completed": False},
            "tool",
            "認証アプリを選びQRコードを読み取ります。",
            {"advice": "", "is_completed": completed_on_retry},
            "QRコードを読み取り設定してください。" if completed_on_retry else "確認できませんでした。",
        ]

        def handle(request):
            body = json.loads(request.content)
            payloads.append(body)
            output = answers[len(payloads) - 1]
            message = {"role": "assistant", "content": None}
            if output == "tool":
                if tool_mode == "native":
                    message["tool_calls"] = [
                        {
                            "id": f"call_{len(payloads)}",
                            "type": "function",
                            "function": {
                                "name": "search_xyz_qa",
                                "arguments": json.dumps({"query": "二段階認証 認証アプリ"}),
                            },
                        }
                    ]
                else:
                    message["content"] = json.dumps({"tool_name": "search_xyz_qa", "query": "二段階認証 認証アプリ"})
            else:
                message["content"] = json.dumps(output, ensure_ascii=False) if isinstance(output, dict) else output
            return httpx.Response(
                200,
                json={
                    "id": "test",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "test-local",
                    "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
                },
            )

        settings = self.settings(tool_mode=tool_mode)
        client = OpenAI(
            api_key="fake",
            base_url=settings.openai_api_base,
            http_client=httpx.Client(transport=httpx.MockTransport(handle)),
        )
        llm = LLM(settings, client=client)
        with patch("src.agent.LLM", return_value=llm):
            result = HelpDeskAgent(settings, tools=LocalSearch().tools()).run_agent("認証アプリの設定手順は？")
        self.assertEqual(llm.calls, 8)
        self.assertEqual(result.subtasks[0].challenge_count, 2)
        self.assertEqual(result.subtasks[0].is_completed, completed_on_retry)
        self.assertEqual(len(result.subtasks[0].tool_results), 2)
        # 再検索のリクエストに孤立したtoolメッセージ・過去のtool_callsが残らないこと。
        retry = payloads[4]["messages"]
        self.assertFalse(any(m["role"] == "tool" or "tool_calls" in m for m in retry))
        self.assertIn("再検索", str(retry))
        if not completed_on_retry:
            self.assertIn("見つかりませんでした", result.subtasks[0].subtask_answer)

    def test_native_retry_graph(self):
        self.run_flow("native")

    def test_json_tool_retry_graph(self):
        self.run_flow("json")

    def test_exhaustion_graph(self):
        self.run_flow("native", completed_on_retry=False)

    def test_request_budget(self):
        llm = LLM(self.settings(max_api_calls=1))
        llm.calls = 1
        with self.assertRaises(RuntimeError):
            llm.complete()

    def test_local_guard_rejects_second_model_without_chat_request(self):
        response = httpx.Response(
            200,
            request=httpx.Request("GET", "http://localhost:1234/api/v0/models"),
            json={
                "data": [{"id": model, "type": "llm", "state": "loaded"} for model in ["test-local", "other-model"]]
            },
        )
        with patch("workshop.checks.fetch_models", return_value=response.json()["data"]):
            with self.assertRaises(ValueError):
                require_loaded_model(self.settings())

    def test_local_guard_rejects_unloaded_selected_model(self):
        response = httpx.Response(
            200,
            request=httpx.Request("GET", "http://localhost:1234/api/v0/models"),
            json={"data": [{"id": "test-local", "type": "llm", "state": "not-loaded"}]},
        )
        with patch("workshop.checks.fetch_models", return_value=response.json()["data"]):
            with self.assertRaises(ValueError):
                require_loaded_model(self.settings())

    def test_local_guard_accepts_single_matching_model(self):
        response = httpx.Response(
            200,
            request=httpx.Request("GET", "http://localhost:1234/api/v0/models"),
            json={
                "data": [
                    {
                        "id": "test-local",
                        "type": "llm",
                        "state": "loaded",
                        "loaded_context_length": 8192,
                        "max_context_length": 262144,
                    }
                ]
            },
        )
        with patch("workshop.checks.fetch_models", return_value=response.json()["data"]):
            current = require_loaded_model(self.settings())
        self.assertEqual(current["loaded_context_length"], 8192)
        self.assertEqual(current["max_context_length"], 262144)

    def test_openrouter_request_contract(self):
        sent = []

        def handle(request):
            sent.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "id": "test",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "vendor/model:free",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": '{"subtasks":["設定手順を調べる"]}'},
                        }
                    ],
                },
            )

        settings = Settings(
            _env_file=None, openai_api_key="fake", openai_model="vendor/model:free", request_interval=0
        )
        client = OpenAI(
            api_key="fake",
            base_url=settings.openai_api_base,
            http_client=httpx.Client(transport=httpx.MockTransport(handle)),
        )
        result = LLM(settings, client=client).structured(
            Plan, model=settings.openai_model, messages=[{"role": "user", "content": "設定手順は？"}]
        )
        self.assertEqual(len(result.subtasks), 1)
        self.assertEqual(sent[0]["model"], "vendor/model:free")
        self.assertEqual(sent[0]["provider"]["max_price"], {"prompt": 0, "completion": 0, "request": 0})
        self.assertTrue(sent[0]["provider"]["require_parameters"])
        self.assertNotIn("models", sent[0])
        self.assertNotIn("reasoning_effort", sent[0])
        self.assertEqual(sent[0]["response_format"]["type"], "json_schema")

    def test_failure_stops_before_next_subtask_request(self):
        sent = []

        def handle(request):
            sent.append(json.loads(request.content))
            plan = len(sent) == 1
            return httpx.Response(
                200,
                json={
                    "id": "test",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "test-local",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop" if plan else "length",
                            "message": {
                                "role": "assistant",
                                "content": '{"subtasks":["タスクA","タスクB"]}' if plan else "打ち切り",
                            },
                        }
                    ],
                },
            )

        settings = self.settings()
        client = OpenAI(
            api_key="fake",
            base_url=settings.openai_api_base,
            http_client=httpx.Client(transport=httpx.MockTransport(handle)),
        )
        llm = LLM(settings, client=client)
        with patch("src.agent.LLM", return_value=llm), self.assertRaises(ValueError):
            HelpDeskAgent(settings, tools=LocalSearch().tools()).run_agent("AとBを調べる")
        self.assertEqual(len(sent), 2)

    def test_json_prompt_mode_validates_without_schema_parameter(self):
        sent = []

        def handle(request):
            sent.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "id": "test",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "test-local",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": '{"unexpected":"invalid plan"}'},
                        }
                    ],
                },
            )

        settings = self.settings(structured_mode="json")
        client = OpenAI(
            api_key="fake",
            base_url=settings.openai_api_base,
            http_client=httpx.Client(transport=httpx.MockTransport(handle)),
        )
        with self.assertRaises(ValueError):
            LLM(settings, client=client).structured(
                Plan, model=settings.openai_model, messages=[{"role": "user", "content": "設定手順は？"}]
            )
        self.assertEqual(len(sent), 1)
        self.assertNotIn("response_format", sent[0])

    def test_cli_and_gui_execution_lock(self):
        with single_run():
            with self.assertRaises(RuntimeError):
                with single_run():
                    self.fail("同時実行を許可してはいけません")
        # 例外後も、次の実行で取得できること。
        with single_run():
            pass

    def test_common_service_records_errors_and_releases_log_handler(self):
        import logging

        count = len(logging.getLogger().handlers)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "workshop").mkdir()
            with (
                patch("workshop.service.ROOT", Path(tmp)),
                patch("workshop.service.require_loaded_model", return_value=None),
                patch("workshop.service.LLM", side_effect=ValueError("接続設定が不正です")),
            ):
                result, path = execute(self.settings(), "preflight")
                saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "error")
        self.assertEqual(saved["api_calls"], 0)
        self.assertEqual(saved["error"], "接続設定が不正です")
        self.assertNotIn("openai_api_key", saved)
        self.assertEqual(len(logging.getLogger().handlers), count)

    def test_import_and_setup_logger_preserve_existing_logging(self):
        import importlib
        import logging
        import src.custom_logger as custom_logger

        root = logging.getLogger()
        handlers, level = list(root.handlers), root.level
        importlib.reload(custom_logger)
        custom_logger.setup_logger("helpdesk.compatibility-test")
        importlib.reload(__import__("src.agent", fromlist=["HelpDeskAgent"]))
        self.assertEqual(root.handlers, handlers)
        self.assertEqual(root.level, level)

    def test_service_closes_clients_and_restores_logging_after_graph_failure(self):
        import logging
        from unittest.mock import Mock

        root = logging.getLogger()
        handlers, level = list(root.handlers), root.level
        agent = Mock()
        agent.llm.calls = 2
        agent.run_agent.side_effect = RuntimeError("graph failed")
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("workshop.service.ROOT", Path(tmp)),
                patch("workshop.service.require_loaded_model", return_value=None),
                patch("workshop.service.LocalSearch") as search,
                patch("workshop.service.HelpDeskAgent", return_value=agent),
            ):
                search.return_value.query_calls = 0
                result, path = execute(self.settings(), "run", "設定手順は？")
                self.assertEqual(result["status"], "error")
                self.assertTrue(path.is_file())
                search.return_value.close.assert_called_once()
                agent.llm.close.assert_called_once()
        self.assertEqual(root.handlers, handlers)
        self.assertEqual(root.level, level)


if __name__ == "__main__":
    unittest.main()
