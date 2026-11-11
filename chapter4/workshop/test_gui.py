"""PySide6画面とワーカーのサービス連携を、画面表示なしで確認する。"""

import logging
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.configs import Settings
from workshop.gui import App


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = self.make_window("LM Studio")

    def make_window(self, provider):
        model = "vendor/test:free" if provider == "OpenRouter" else "test-local"
        base_url = "https://openrouter.ai/api/v1" if provider == "OpenRouter" else "http://localhost:1234/v1"
        initial = Settings(
            _env_file=None,
            openai_api_base=base_url,
            openai_model=model,
            openai_api_key="test-key",
            save_full_logs=True,
        )
        with (
            patch("workshop.gui.Settings", return_value=initial),
            patch("workshop.gui.QTimer.singleShot"),
        ):
            return App()

    def tearDown(self):
        self.dispose_window()

    def dispose_window(self):
        self.window.timer.stop()
        logging.getLogger().removeHandler(self.window.handler)
        self.window.handler.close()
        self.window.deleteLater()
        self.qt_app.processEvents()

    def finish(self):
        self.window.worker.join(timeout=3)
        self.assertFalse(self.window.worker.is_alive())
        self.window.poll()
        self.assertFalse(self.window.busy)

    def test_startup_reads_loaded_model_and_gui_context(self):
        models = [{"id": "test-local", "type": "llm", "state": "loaded", "loaded_context_length": 8192}]
        with patch("workshop.gui.list_models", return_value=models) as fetch:
            self.window.startup_models()
            self.finish()
        self.assertEqual(fetch.call_args.kwargs["timeout"], 3)
        self.assertEqual(self.window.model_box.currentText(), "test-local")
        self.assertIn("8192", self.window.context_label.text())
        self.assertEqual(self.window.model_catalogues["LM Studio"], models)

    def test_startup_server_down_keeps_gui_usable(self):
        with patch("workshop.gui.list_models", side_effect=ConnectionError("server down")):
            self.window.startup_models()
            self.finish()
        self.assertIn("モデル一覧を更新", self.window.status_label.text())
        self.assertTrue(self.window.run_button.isEnabled())

    def test_openrouter_status_explains_schema_mismatch_and_json_compatibility(self):
        self.window.provider_combo.setCurrentText("OpenRouter")
        self.window.model_box.setCurrentText("vendor/test:free")
        self.window.model_catalogues["OpenRouter"] = [
            {"id": "vendor/test:free", "supported_parameters": ["tools", "tool_choice"]}
        ]
        self.window.update_model_status()
        self.assertIn("jsonへ変更", self.window.context_label.text())
        self.window.structured_mode_combo.setCurrentText("json")
        self.window.update_model_status()
        self.assertIn("現在の設定に対応", self.window.context_label.text())

    def test_manual_refresh_and_common_execution(self):
        models = [{"id": "test-local", "type": "llm", "state": "loaded", "loaded_context_length": 4096}]
        with patch("workshop.gui.list_models", return_value=models):
            self.window.get_models()
            self.finish()
        self.window.question.setPlainText("設定手順は？")
        result = {"status": "passed", "answer": "確認済みの回答", "api_calls": 5, "elapsed_seconds": 1.0}
        with patch("workshop.gui.execute", return_value=(result, "result.json")) as execute:
            self.window.run("run")
            self.finish()
        self.assertEqual(execute.call_args.args[1:], ("run", "設定手順は？"))
        self.assertEqual(execute.call_args.args[0].openai_model, "test-local")
        self.assertTrue(execute.call_args.args[0].save_full_logs)
        self.assertEqual(self.window.answer.toPlainText(), "確認済みの回答")
        self.assertIn("API 5回", self.window.status_label.text())

    def test_startup_does_not_switch_openrouter_selection(self):
        self.dispose_window()
        self.window = self.make_window("OpenRouter")
        original_model = self.window.model_box.currentText()
        with patch("workshop.gui.list_models", return_value=[{"id": "test-local", "type": "llm"}]):
            self.window.startup_models()
            self.finish()
        self.assertEqual(self.window.model_box.currentText(), original_model)
        self.assertEqual(self.window.model_catalogues["LM Studio"][0]["id"], "test-local")

    def test_catalogue_separates_available_chat_and_embedding_models(self):
        models = [
            {"id": "test-local", "type": "llm", "state": "loaded"},
            {"id": "other-chat", "type": "llm", "state": "not-loaded"},
            {"id": "other-embedding", "type": "embeddings", "state": "not-loaded"},
        ]
        with patch("workshop.gui.list_models", return_value=models):
            self.window.get_models()
            self.finish()
        chat_ids = [self.window.model_box.itemText(index) for index in range(self.window.model_box.count())]
        embedding_ids = [self.window.embedding_box.itemText(index) for index in range(self.window.embedding_box.count())]
        self.assertEqual(chat_ids, ["test-local", "other-chat"])
        self.assertEqual(embedding_ids, ["other-embedding"])


if __name__ == "__main__":
    unittest.main()
