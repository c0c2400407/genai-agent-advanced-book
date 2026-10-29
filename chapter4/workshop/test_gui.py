"""ネイティブ画面を操作せず、GUIのワーカーとサービス連携を確認する。"""

import queue
import unittest
from unittest.mock import Mock, patch

from src.configs import Settings
from workshop.gui import App


class GuiTests(unittest.TestCase):
    def setUp(self):
        messages = patch("workshop.gui.messagebox.showerror")
        messages.start()
        self.addCleanup(messages.stop)

    def app(self):
        app = App.__new__(App)
        app.root = Mock()
        app.events = queue.Queue()
        app.busy = False
        app.controls = [(Mock(), "normal"), (Mock(), "readonly")]
        app.handler = Mock()
        app.initial = Settings(_env_file=None, openai_api_base="http://localhost:1234/v1", openai_model="test-local")
        for name, value in [
            ("provider", "LM Studio"),
            ("base_url", "http://localhost:1234/v1"),
            ("model", "test-local"),
            ("api_key", "test-key"),
            ("tool_mode", "native"),
            ("structured_mode", "schema"),
            ("search_backend", "TF-IDF（文字一致）"),
            ("embedding_model", "test-embedding"),
            ("embedding_url", "http://localhost:1234/v1"),
            ("log_consent", True),
            ("subtasks", "1"),
            ("output_tokens", "1200"),
        ]:
            variable = Mock()
            variable.get.return_value = value
            setattr(app, name, variable)
        for name in [
            "status",
            "question",
            "logs",
            "answer",
            "details",
            "context",
            "model_box",
            "embedding_box",
            "embedding_url_entry",
        ]:
            setattr(app, name, Mock())
        app.question.get.return_value = "設定手順は？"
        app.put = Mock()
        app.model_catalogues = {"LM Studio": [], "OpenRouter": []}
        return app

    def finish(self, app):
        app.worker.join(timeout=3)
        self.assertFalse(app.worker.is_alive())
        app.poll()
        self.assertFalse(app.busy)

    def test_startup_reads_loaded_model_and_gui_context(self):
        app = self.app()
        models = [{"id": "test-local", "type": "llm", "state": "loaded", "loaded_context_length": 8192}]
        with patch("workshop.gui.list_models", return_value=models) as fetch:
            app.startup_models()
            self.finish(app)
        self.assertEqual(fetch.call_args.kwargs["timeout"], 3)
        app.model_box.configure.assert_any_call(values=["test-local"])
        self.assertIn("8192", app.context.set.call_args.args[0])
        self.assertEqual(app.model_catalogues["LM Studio"], models)

    def test_startup_server_down_keeps_gui_usable(self):
        app = self.app()
        with patch("workshop.gui.list_models", side_effect=ConnectionError("server down")):
            app.startup_models()
            self.finish(app)
        self.assertIn("モデル一覧を更新", app.status.set.call_args.args[0])
        self.assertFalse(any(call.args[0] is app.answer for call in app.put.call_args_list))

    def test_manual_refresh_and_common_execution(self):
        app = self.app()
        with patch("workshop.gui.list_models", return_value=[{"id": "test-local", "loaded_context_length": 4096}]):
            app.get_models()
            self.finish(app)
        result = {"status": "passed", "answer": "確認済みの回答", "api_calls": 5, "elapsed_seconds": 1.0}
        with patch("workshop.gui.execute", return_value=(result, "result.json")) as execute:
            app.run("run")
            self.finish(app)
        self.assertEqual(execute.call_args.args[1:], ("run", "設定手順は？"))
        self.assertEqual(execute.call_args.args[0].openai_model, "test-local")
        self.assertTrue(execute.call_args.args[0].save_full_logs)
        app.put.assert_any_call(app.answer, "確認済みの回答")
        self.assertIn("API 5回", app.status.set.call_args.args[0])

    def test_startup_does_not_switch_openrouter_selection(self):
        app = self.app()
        app.provider.get.return_value = "OpenRouter"
        with patch("workshop.gui.list_models", return_value=[{"id": "local", "loaded_context_length": 8192}]):
            app.startup_models()
            self.finish(app)
        app.model.set.assert_not_called()
        self.assertEqual(app.model_catalogues["LM Studio"][0]["id"], "local")

    def test_catalogue_separates_available_chat_and_embedding_models(self):
        app = self.app()
        models = [
            {"id": "test-local", "type": "llm", "state": "loaded", "loaded_context_length": 8192},
            {"id": "other-chat", "type": "llm", "state": "not-loaded"},
            {"id": "other-embedding", "type": "embeddings", "state": "not-loaded"},
        ]
        with patch("workshop.gui.list_models", return_value=models):
            app.get_models()
            self.finish(app)
        app.model_box.configure.assert_any_call(values=["test-local", "other-chat"])
        app.embedding_box.configure.assert_any_call(values=["other-embedding"])


if __name__ == "__main__":
    unittest.main()
