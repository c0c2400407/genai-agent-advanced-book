"""PySide6によるGUI。処理はservice.pyへ委譲する。"""

import json
import logging
import queue
import sys
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.configs import Settings
from src.custom_logger import configure_logging
from src.security import RedactingFormatter, ensure_runtime, public_error, reveal, validate_question
from workshop.checks import capability_problem
from workshop.service import DEFAULT_QUESTION, execute, list_models, prepare_index

SEARCH_LABELS = {"tfidf": "TF-IDF（文字一致）", "lmstudio": "LM Studio Embedding"}
logger = logging.getLogger(__name__)


class QueueLogHandler(logging.Handler):
    def __init__(self, events, secrets=()):
        super().__init__()
        self.events = events
        self.setLevel(logging.INFO)
        self.setFormatter(RedactingFormatter("%(asctime)s %(message)s", secrets, datefmt="%H:%M:%S"))

    def emit(self, record):
        self.events.put(("log", self.format(record)))


class SecretLineEdit(QLineEdit):
    """Password field with clipboard diagnostics that never log clipboard text."""

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            clipboard = QApplication.clipboard()
            mime_data = clipboard.mimeData()
            has_text = bool(mime_data and mime_data.hasText())
            logger.info("API_KEY_PASTE event=received source=qt")
            super().keyPressEvent(event)
            if has_text:
                logger.info("API_KEY_PASTE result=success source=qt")
            else:
                logger.warning("API_KEY_PASTE result=failed source=qt reason=clipboard_empty")
                QApplication.beep()
            return
        super().keyPressEvent(event)


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.events = queue.Queue()
        self.busy = False
        self.controls = []
        self.model_catalogues = {"LM Studio": [], "OpenRouter": []}
        self.initial = Settings()
        self.active_secrets = [self.initial.openai_api_key, self.initial.embedding_api_key]
        self.handler = QueueLogHandler(self.events, self.active_secrets)
        logging.getLogger().addHandler(self.handler)

        self.setWindowTitle("第4章 ヘルプデスクAIエージェント")
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        width = min(1060, available.width() - 80) if available else 1060
        height = min(800, available.height() - 90) if available else 800
        self.resize(max(900, width), max(650, height))
        self.setMinimumSize(900, 650)
        self.setFont(QFont("Yu Gothic UI", 10))

        self._build_ui()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(100)
        logger.info("APP_READY provider=%s gui=PySide6", self.provider_combo.currentText())
        QTimer.singleShot(200, self.startup_models)

    def _build_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(18, 18, 18, 12)

        title = QLabel("ヘルプデスクAIエージェント")
        title.setStyleSheet("font-size: 21pt; font-weight: bold;")
        outer.addWidget(title)
        outer.addWidget(QLabel("質問の分解 → 検索 → 回答 → 評価・再試行 → 最終回答"))

        config = QGroupBox("1  接続先")
        grid = QGridLayout(config)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 2)
        settings = self.initial
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["LM Studio", "OpenRouter"])
        self.provider_combo.setCurrentText(
            "OpenRouter" if "openrouter.ai" in settings.openai_api_base else "LM Studio"
        )
        self.model_box = QComboBox()
        self.model_box.setEditable(True)
        self.model_box.setCurrentText(settings.openai_model)
        self.base_url_entry = QLineEdit(settings.openai_api_base)
        self.api_key_entry = SecretLineEdit()
        self.api_key_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_entry.setText(reveal(settings.openai_api_key))
        self.api_key_entry.setPlaceholderText("OpenRouter APIキー")

        grid.addWidget(QLabel("接続先"), 0, 0)
        grid.addWidget(self.provider_combo, 0, 1)
        grid.addWidget(QLabel("呼び出すモデル"), 0, 2)
        grid.addWidget(self.model_box, 0, 3)
        grid.addWidget(QLabel("API URL"), 1, 0)
        grid.addWidget(self.base_url_entry, 1, 1, 1, 3)
        grid.addWidget(QLabel("APIキー"), 2, 0)
        grid.addWidget(self.api_key_entry, 2, 1, 1, 3)
        grid.addWidget(
            QLabel("キーは画面内で使用します。画面の入力内容は設定ファイルに保存しません。"), 3, 0, 1, 4
        )
        self.context_label = QLabel("LM StudioのContext Lengthは、LM StudioのGUIで設定して再ロードします。")
        self.context_label.setWordWrap(True)
        grid.addWidget(self.context_label, 4, 0, 1, 4)

        self.search_backend_combo = QComboBox()
        self.search_backend_combo.addItems(list(SEARCH_LABELS.values()))
        self.search_backend_combo.setCurrentText(SEARCH_LABELS[settings.search_backend])
        self.embedding_box = QComboBox()
        self.embedding_box.setEditable(True)
        self.embedding_box.setCurrentText(settings.embedding_model)
        self.embedding_url_entry = QLineEdit(settings.embedding_base_url)
        grid.addWidget(QLabel("検索方式"), 5, 0)
        grid.addWidget(self.search_backend_combo, 5, 1)
        grid.addWidget(QLabel("Embeddingモデル"), 5, 2)
        grid.addWidget(self.embedding_box, 5, 3)
        grid.addWidget(QLabel("Embedding URL"), 6, 0)
        grid.addWidget(self.embedding_url_entry, 6, 1, 1, 3)

        config_buttons = QHBoxLayout()
        self.models_button = QPushButton("モデル一覧を更新")
        self.preflight_button = QPushButton("接続・機能確認（3リクエスト）")
        self.index_button = QPushButton("検索データを準備")
        for button in (self.models_button, self.preflight_button, self.index_button):
            config_buttons.addWidget(button)
            self.controls.append(button)
        config_buttons.addStretch(1)
        grid.addLayout(config_buttons, 7, 0, 1, 4)
        outer.addWidget(config)

        question_group = QGroupBox("2  質問")
        question_layout = QVBoxLayout(question_group)
        self.question = QPlainTextEdit()
        self.question.setMaximumHeight(100)
        self.question.setPlainText(DEFAULT_QUESTION)
        question_layout.addWidget(self.question)
        options = QHBoxLayout()
        self.tool_mode_combo = QComboBox()
        self.tool_mode_combo.addItems(["native", "json"])
        self.tool_mode_combo.setCurrentText(settings.tool_mode)
        self.structured_mode_combo = QComboBox()
        self.structured_mode_combo.addItems(["schema", "json"])
        self.structured_mode_combo.setCurrentText(settings.structured_mode)
        self.subtasks_spin = QSpinBox()
        self.subtasks_spin.setRange(1, 2)
        self.subtasks_spin.setValue(settings.max_subtasks)
        self.output_tokens_spin = QSpinBox()
        self.output_tokens_spin.setRange(128, 8192)
        self.output_tokens_spin.setValue(settings.max_output_tokens)
        self.save_logs_check = QCheckBox(
            "質問・回答・検索結果をファイルに保存する（共有する前に内容を確認してください）"
        )
        self.save_logs_check.setChecked(settings.save_full_logs)
        self.run_button = QPushButton("質問を実行")

        for label, widget in (
            ("ツール", self.tool_mode_combo),
            ("構造化出力", self.structured_mode_combo),
            ("サブタスク上限", self.subtasks_spin),
            ("出力上限", self.output_tokens_spin),
        ):
            options.addWidget(QLabel(label))
            options.addWidget(widget)
            self.controls.append(widget)
        options.addStretch(1)
        options.addWidget(self.run_button)
        question_layout.addLayout(options)
        question_layout.addWidget(self.save_logs_check)
        self.controls.extend([self.run_button, self.save_logs_check])
        outer.addWidget(question_group)

        self.tabs = QTabWidget()
        self.answer = self._new_tab("回答")
        self.details = self._new_tab("検索・評価の詳細")
        self.logs = self._new_tab("経過ログ")
        outer.addWidget(self.tabs, 1)
        self.status_label = QLabel("準備完了。初回は検索データの準備と接続・機能確認を実行してください。")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        for widget in (self.provider_combo, self.model_box, self.base_url_entry, self.api_key_entry,
                       self.search_backend_combo, self.embedding_box, self.embedding_url_entry):
            self.controls.append(widget)

        self.provider_combo.currentTextChanged.connect(self.change_provider)
        self.model_box.currentTextChanged.connect(self.update_model_status)
        self.search_backend_combo.currentTextChanged.connect(self.update_search_state)
        self.tool_mode_combo.currentTextChanged.connect(self.update_model_status)
        self.structured_mode_combo.currentTextChanged.connect(self.update_model_status)
        self.models_button.clicked.connect(self.get_models)
        self.preflight_button.clicked.connect(lambda: self.run("preflight"))
        self.index_button.clicked.connect(self.index)
        self.run_button.clicked.connect(lambda: self.run("run"))
        self.update_search_state()
        logger.info("PROVIDER_CHANGED provider=%s api_key_present=%s", self.provider_combo.currentText(), bool(self.api_key_entry.text()))

    def _new_tab(self, label):
        widget = QPlainTextEdit()
        widget.setReadOnly(True)
        self.tabs.addTab(widget, label)
        return widget

    @staticmethod
    def put(widget, text, append=False):
        if append:
            widget.appendPlainText(text.rstrip("\n"))
        else:
            widget.setPlainText(text)
        cursor = widget.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        widget.setTextCursor(cursor)

    def change_provider(self, provider=None):
        provider = provider or self.provider_combo.currentText()
        local = provider == "LM Studio"
        self.base_url_entry.setText("http://localhost:1234/v1" if local else "https://openrouter.ai/api/v1")
        self.model_box.setCurrentText("" if local else "liquid/lfm-2.5-2.6b:free")
        cached = self.model_catalogues[provider]
        chat_models = [m for m in cached if m.get("type", "llm") != "embeddings"]
        loaded = [m for m in chat_models if m.get("state") == "loaded"]
        self.model_box.clear()
        self.model_box.addItems([model["id"] for model in chat_models])
        if local and len(loaded) == 1:
            self.model_box.setCurrentText(loaded[0]["id"])
        elif not local:
            self.model_box.setCurrentText("liquid/lfm-2.5-2.6b:free")
        self.api_key_entry.setText("lm-studio" if local else "")
        logger.info("PROVIDER_CHANGED provider=%s api_key_present=%s", provider, bool(self.api_key_entry.text()))
        self.context_label.setText(
            "LM StudioのGUIで使用する1モデルをロードし、「モデル一覧を更新」を押してください。"
            if local
            else "固定の無料モデルIDを選択してください。候補の実APIでの最終確認は必要です。"
        )
        self.update_model_status()

    def update_model_status(self, *_args):
        if self.provider_combo.currentText() != "LM Studio":
            selected = next(
                (m for m in self.model_catalogues["OpenRouter"] if m["id"] == self.model_box.currentText()), None
            )
            if selected:
                parameters = selected.get("supported_parameters") or []
                if not isinstance(parameters, list) or not all(isinstance(item, str) for item in parameters):
                    parameters = []
                tools = "対応" if {"tools", "tool_choice"}.issubset(parameters) else "未確認"
                schema = "対応" if {"response_format", "structured_outputs"}.issubset(parameters) else "未確認"
                problem = capability_problem(selected, self.tool_mode_combo.currentText(), self.structured_mode_combo.currentText())
                self.context_label.setText(
                    f"公開情報: ツール {tools} / schema {schema}。{problem or '現在の設定に対応。配信状況やアカウント制限は実接続で確認します。'}"
                )
            else:
                self.context_label.setText("対応機能は未確認です。「モデル一覧を更新」で確認してください。")
            return
        selected = next((m for m in self.model_catalogues["LM Studio"] if m["id"] == self.model_box.currentText()), None)
        if selected:
            state = "ロード済み" if selected.get("state") == "loaded" else "未ロード（LM StudioのGUIで切り替えてください）"
            self.context_label.setText(
                f"モデル状態: {state} / Context Length: {selected.get('loaded_context_length') or '未設定'} tokens"
            )

    def update_search_state(self, *_args):
        enabled = self.search_backend_combo.currentText() == SEARCH_LABELS["lmstudio"]
        self.embedding_box.setEnabled(enabled and not self.busy)
        self.embedding_url_entry.setEnabled(enabled and not self.busy)

    def settings(self):
        api_key = self.api_key_entry.text().strip()
        logger.info("API_KEY_STATE provider=%s present=%s", self.provider_combo.currentText(), bool(api_key))
        values = self.initial.model_dump()
        values.update(
            openai_api_base=self.base_url_entry.text().strip(),
            openai_model=self.model_box.currentText().strip(),
            openai_api_key=api_key,
            tool_mode=self.tool_mode_combo.currentText(),
            structured_mode=self.structured_mode_combo.currentText(),
            max_subtasks=self.subtasks_spin.value(),
            max_output_tokens=self.output_tokens_spin.value(),
            search_backend="lmstudio" if self.search_backend_combo.currentText() == SEARCH_LABELS["lmstudio"] else "tfidf",
            embedding_model=self.embedding_box.currentText().strip(),
            embedding_base_url=self.embedding_url_entry.text().strip(),
            save_full_logs=self.save_logs_check.isChecked(),
            reasoning_effort="none" if self.provider_combo.currentText() == "LM Studio" else None,
        )
        result = Settings(_env_file=None, **values)
        self.handler.formatter.secrets = [result.openai_api_key, result.embedding_api_key]
        self.active_secrets = [result.openai_api_key, result.embedding_api_key]
        return result

    def start(self, work, message="実行中…同じモデルを1件ずつ呼び出しています。", secrets=None):
        if self.busy:
            return
        self.busy = True
        logger.info("UI_TASK status=started controls=disabled")
        self.status_label.setText(message)
        for widget in self.controls:
            widget.setEnabled(False)
        self.question.setEnabled(False)
        active_secrets = list(secrets or self.active_secrets)

        def worker():
            try:
                self.events.put(("done", work()))
            except Exception as exc:
                logger.error("UI_TASK status=failed error_type=%s", type(exc).__name__)
                self.events.put(("error", public_error(exc, active_secrets)))

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    def run(self, command):
        try:
            settings = self.settings()
            question = self.question.toPlainText().strip()
            if command == "run":
                validate_question(question)
        except Exception as exc:
            QMessageBox.critical(self, "設定の確認", public_error(exc, [self.api_key_entry.text()]))
            return
        self.put(self.answer, "実行中…")
        self.put(self.details, "")
        self.start(lambda: ("execution", execute(settings, command, question)), secrets=[settings.openai_api_key, settings.embedding_api_key])

    def get_models(self):
        try:
            settings = self.settings()
        except Exception as exc:
            QMessageBox.critical(self, "設定の確認", public_error(exc, [self.api_key_entry.text()]))
            return
        provider = self.provider_combo.currentText()
        self.start(
            lambda: ("models", {"provider": provider, "items": list_models(settings)}),
            "モデル一覧を取得中…",
            secrets=[settings.openai_api_key, settings.embedding_api_key],
        )

    def startup_models(self):
        if self.busy:
            return
        settings = self.initial.model_copy(
            update={
                "openai_api_base": self.initial.openai_api_base
                if self.provider_combo.currentText() == "LM Studio"
                else "http://localhost:1234/v1",
            }
        )

        def fetch():
            try:
                items = list_models(settings, timeout=3)
                logger.info("STARTUP_MODEL_CHECK result=success count=%d", len(items))
                return "models", {"provider": "LM Studio", "items": items}
            except Exception as exc:
                logger.warning("STARTUP_MODEL_CHECK result=failed error_type=%s", type(exc).__name__)
                return "startup_unavailable", None

        self.start(fetch, "起動時にLM Studioのモデル一覧を確認中…", secrets=[settings.openai_api_key])

    def index(self):
        try:
            settings = self.settings()
        except Exception as exc:
            QMessageBox.critical(self, "設定の確認", public_error(exc, [self.api_key_entry.text()]))
            return
        self.start(
            lambda: ("index", prepare_index(settings)),
            "検索データを準備中…Embedding使用時は文書をベクトル化します。",
            secrets=[settings.openai_api_key, settings.embedding_api_key],
        )

    def poll(self):
        try:
            while True:
                event, value = self.events.get_nowait()
                if event == "log":
                    self.put(self.logs, value + "\n", append=True)
                    continue
                self.busy = False
                logger.info("UI_TASK status=%s controls=enabled", "finished" if event == "done" else "failed")
                for widget in self.controls:
                    widget.setEnabled(True)
                self.question.setEnabled(True)
                self.update_search_state()
                if event == "error":
                    self.status_label.setText("停止しました。設定と経過ログを確認してください。")
                    self.put(self.answer, value)
                    continue
                kind, result = value
                if kind == "startup_unavailable":
                    self.status_label.setText("準備完了。LM Studio起動後は「モデル一覧を更新」で取得できます。")
                    continue
                if kind == "execution":
                    data, path = result
                    self.put(
                        self.answer,
                        data.get(
                            "answer",
                            data.get("error", json.dumps(data.get("checks", {}), ensure_ascii=False, indent=2)),
                        ),
                    )
                    self.put(self.details, json.dumps(data, ensure_ascii=False, indent=2))
                    self.status_label.setText(
                        f"{data['status']} / API {data['api_calls']}回 / {data['elapsed_seconds']}秒 / 保存先: {path}"
                    )
                    if data.get("local_model"):
                        self.context_label.setText(
                            f"現在のロード済みContext Length: {data['local_model']['loaded_context_length']} tokens。変更はLM StudioのGUIで行います。"
                        )
                elif kind == "models":
                    provider, items = result["provider"], result["items"]
                    self.model_catalogues[provider] = items
                    chat_models = [m for m in items if m.get("type", "llm") != "embeddings"]
                    if provider == "LM Studio":
                        embedding_models = [m for m in items if m.get("type") == "embeddings"]
                        self.embedding_box.clear()
                        self.embedding_box.addItems([m["id"] for m in embedding_models])
                    if self.provider_combo.currentText() == provider:
                        current_model = self.model_box.currentText()
                        self.model_box.clear()
                        self.model_box.addItems([m["id"] for m in chat_models])
                        loaded = [m for m in chat_models if m.get("state") == "loaded"]
                        if provider == "LM Studio" and len(loaded) == 1 and not any(
                            m["id"] == current_model for m in chat_models
                        ):
                            current_model = loaded[0]["id"]
                        self.model_box.setCurrentText(current_model)
                        self.update_model_status()
                        self.status_label.setText(f"言語モデルを{len(chat_models)}件取得しました。未ロードのものはLM Studio側で切り替えてください。")
                    else:
                        self.status_label.setText(
                            "LM Studioのモデル一覧を取得しました。接続先をLM Studioに切り替えると選択できます。"
                        )
                else:
                    self.status_label.setText(f"検索データを準備しました: {result}")
        except queue.Empty:
            pass

    def closeEvent(self, event):
        if self.busy:
            QMessageBox.information(self, "実行中", "処理の完了を待ってから閉じてください。")
            event.ignore()
            return
        logging.getLogger().removeHandler(self.handler)
        self.handler.close()
        event.accept()


def launch():
    configure_logging()
    ensure_runtime()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("第4章 ヘルプデスクAIエージェント")
    window = App()
    window.show()
    app.exec()
