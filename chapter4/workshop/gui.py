"""標準ライブラリのTkinterによる薄い画面。実行はservice.pyへ委譲する。"""

import json
import logging
import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from src.configs import Settings
from src.custom_logger import configure_logging
from workshop.service import DEFAULT_QUESTION, execute, list_models, prepare_index
from src.security import reveal, RedactingFormatter, public_error, validate_question, ensure_runtime

SEARCH_LABELS = {"tfidf": "TF-IDF（文字一致）", "lmstudio": "LM Studio Embedding"}


class QueueLogHandler(logging.Handler):
    def __init__(self, events, secrets=()):
        super().__init__()
        self.events = events
        self.setLevel(logging.INFO)
        self.setFormatter(RedactingFormatter("%(asctime)s %(message)s", secrets, datefmt="%H:%M:%S"))

    def emit(self, record):
        self.events.put(("log", self.format(record)))


class App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.busy = False
        self.controls = []
        self.model_catalogues = {"LM Studio": [], "OpenRouter": []}
        settings = Settings()
        self.handler = QueueLogHandler(self.events, [settings.openai_api_key, settings.embedding_api_key])
        logging.getLogger().addHandler(self.handler)
        self.initial = settings
        root.title("第4章 ヘルプデスクAIエージェント")
        width = min(1060, root.winfo_screenwidth() - 80)
        height = min(800, root.winfo_screenheight() - 90)
        root.geometry(f"{width}x{height}")
        root.minsize(min(900, width), min(650, height))
        root.option_add("*Font", ("Yu Gothic UI", 10))
        root.protocol("WM_DELETE_WINDOW", self.close)
        frame = ttk.Frame(root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="ヘルプデスクAIエージェント", font=("Yu Gothic UI", 21, "bold")).pack(anchor="w")
        ttk.Label(frame, text="質問の分解 → 検索 → 回答 → 評価・再試行 → 最終回答").pack(anchor="w", pady=(2, 12))

        config = ttk.LabelFrame(frame, text="1  接続先", padding=10)
        config.pack(fill="x")
        config.columnconfigure(1, weight=1)
        config.columnconfigure(3, weight=2)
        self.provider = tk.StringVar(
            value="OpenRouter" if "openrouter.ai" in settings.openai_api_base else "LM Studio"
        )
        self.base_url = tk.StringVar(value=settings.openai_api_base)
        self.model = tk.StringVar(value=settings.openai_model)
        self.api_key = tk.StringVar(value=reveal(settings.openai_api_key))
        self.log_consent = tk.BooleanVar(value=settings.save_full_logs)
        self.tool_mode = tk.StringVar(value=settings.tool_mode)
        self.structured_mode = tk.StringVar(value=settings.structured_mode)
        self.subtasks = tk.StringVar(value=str(settings.max_subtasks))
        self.output_tokens = tk.StringVar(value=str(settings.max_output_tokens))
        self.search_backend = tk.StringVar(value=SEARCH_LABELS[settings.search_backend])
        self.embedding_model = tk.StringVar(value=settings.embedding_model)
        self.embedding_url = tk.StringVar(value=settings.embedding_base_url)
        ttk.Label(config, text="接続先").grid(row=0, column=0, sticky="w", padx=(0, 8))
        provider = ttk.Combobox(
            config, textvariable=self.provider, values=["LM Studio", "OpenRouter"], state="readonly", width=15
        )
        provider.grid(row=0, column=1, sticky="ew", padx=(0, 14))
        provider.bind("<<ComboboxSelected>>", self.change_provider)
        ttk.Label(config, text="呼び出すモデル").grid(row=0, column=2, sticky="w", padx=(0, 8))
        self.model_box = ttk.Combobox(config, textvariable=self.model)
        self.model_box.grid(row=0, column=3, sticky="ew")
        self.model_box.bind("<<ComboboxSelected>>", self.update_model_status)
        self.controls.extend([(provider, "readonly"), (self.model_box, "normal")])
        for row, label, variable, masked in [(1, "API URL", self.base_url, False), (2, "APIキー", self.api_key, True)]:
            ttk.Label(config, text=label).grid(row=row, column=0, sticky="w", pady=5)
            entry = ttk.Entry(config, textvariable=variable, show="●" if masked else "")
            entry.grid(row=row, column=1, columnspan=3, sticky="ew", pady=5)
            self.controls.append((entry, "normal"))
        ttk.Label(config, text="キーは画面内で使用します。画面の入力内容は設定ファイルに保存しません。").grid(
            row=3, column=0, columnspan=4, sticky="w"
        )
        self.context = tk.StringVar(value="LM StudioのContext Lengthは、LM StudioのGUIで設定して再ロードします。")
        ttk.Label(config, textvariable=self.context, wraplength=950).grid(
            row=4, column=0, columnspan=4, sticky="w", pady=(6, 2)
        )
        ttk.Label(config, text="検索方式").grid(row=5, column=0, sticky="w", pady=5)
        backend_box = ttk.Combobox(
            config, textvariable=self.search_backend, values=list(SEARCH_LABELS.values()), state="readonly"
        )
        backend_box.grid(row=5, column=1, sticky="ew", padx=(0, 14))
        backend_box.bind("<<ComboboxSelected>>", self.update_search_state)
        ttk.Label(config, text="Embeddingモデル").grid(row=5, column=2, sticky="w", padx=(0, 8))
        self.embedding_box = ttk.Combobox(config, textvariable=self.embedding_model)
        self.embedding_box.grid(row=5, column=3, sticky="ew")
        ttk.Label(config, text="Embedding URL").grid(row=6, column=0, sticky="w", pady=5)
        self.embedding_url_entry = ttk.Entry(config, textvariable=self.embedding_url)
        self.embedding_url_entry.grid(row=6, column=1, columnspan=3, sticky="ew")
        self.controls.extend(
            [(backend_box, "readonly"), (self.embedding_box, "normal"), (self.embedding_url_entry, "normal")]
        )
        self.update_search_state()
        buttons = ttk.Frame(config)
        buttons.grid(row=7, column=0, columnspan=4, sticky="w", pady=(6, 0))
        for label, command in [
            ("モデル一覧を更新", self.get_models),
            ("接続・機能確認（3リクエスト）", lambda: self.run("preflight")),
            ("検索データを準備", self.index),
        ]:
            button = ttk.Button(buttons, text=label, command=command)
            button.pack(side="left", padx=(0, 8))
            self.controls.append((button, "normal"))

        question_frame = ttk.LabelFrame(frame, text="2  質問", padding=10)
        question_frame.pack(fill="x", pady=12)
        self.question = scrolledtext.ScrolledText(question_frame, height=3, wrap="word", font=("Yu Gothic UI", 11))
        self.question.pack(fill="x")
        self.question.insert("1.0", DEFAULT_QUESTION)
        options = ttk.Frame(question_frame)
        options.pack(fill="x", pady=(10, 0))
        for label, variable, values in [
            ("ツール", self.tool_mode, ["native", "json"]),
            ("構造化出力", self.structured_mode, ["schema", "json"]),
        ]:
            ttk.Label(options, text=label).pack(side="left", padx=(0, 5))
            widget = ttk.Combobox(options, textvariable=variable, values=values, state="readonly", width=8)
            widget.pack(side="left", padx=(0, 14))
            self.controls.append((widget, "readonly"))
        for label, variable, minimum, maximum, width in [
            ("サブタスク上限", self.subtasks, 1, 2, 3),
            ("出力上限", self.output_tokens, 128, 8192, 6),
        ]:
            ttk.Label(options, text=label).pack(side="left", padx=(0, 5))
            widget = ttk.Spinbox(options, textvariable=variable, from_=minimum, to=maximum, width=width)
            widget.pack(side="left", padx=(0, 14))
            self.controls.append((widget, "normal"))
        button = ttk.Button(options, text="質問を実行", command=lambda: self.run("run"))
        button.pack(side="right")
        self.controls.append((button, "normal"))

        consent = ttk.Checkbutton(
            question_frame,
            text="質問・回答・検索結果をファイルに保存する（共有する前に内容を確認してください）",
            variable=self.log_consent,
        )
        consent.pack(anchor="w", pady=(6, 0))
        self.controls.append((consent, "normal"))

        notebook = ttk.Notebook(frame)
        notebook.pack(fill="both", expand=True)
        self.answer = self.tab(notebook, "回答")
        self.details = self.tab(notebook, "検索・評価の詳細")
        self.logs = self.tab(notebook, "経過ログ")
        self.status = tk.StringVar(value="準備完了。初回は検索データの準備と接続・機能確認を実行してください。")
        ttk.Label(frame, textvariable=self.status, wraplength=1000).pack(
            side="bottom", fill="x", pady=(10, 0), before=notebook
        )
        root.after(100, self.poll)
        root.after(200, self.startup_models)

    def tab(self, notebook, name):
        widget = scrolledtext.ScrolledText(notebook, wrap="word", state="disabled", font=("Yu Gothic UI", 10))
        notebook.add(widget, text=name)
        return widget

    def put(self, widget, text, append=False):
        widget.configure(state="normal")
        if not append:
            widget.delete("1.0", "end")
        widget.insert("end", text)
        widget.see("end")
        widget.configure(state="disabled")

    def change_provider(self, _event=None):
        local = self.provider.get() == "LM Studio"
        self.base_url.set("http://localhost:1234/v1" if local else "https://openrouter.ai/api/v1")
        self.model.set("" if local else "liquid/lfm-2.5-2.6b:free")
        cached = self.model_catalogues[self.provider.get()]
        chat_models = [m for m in cached if m.get("type", "llm") != "embeddings"]
        loaded = [m for m in chat_models if m.get("state") == "loaded"]
        self.model_box.configure(values=[model["id"] for model in chat_models])
        if local and len(loaded) == 1:
            self.model.set(loaded[0]["id"])
        self.api_key.set("lm-studio" if local else "")
        self.context.set(
            "LM StudioのGUIで使用する1モデルをロードし、「モデル一覧を更新」を押してください。"
            if local
            else "固定の無料モデルIDを選択してください。候補の実APIでの最終確認は必要です。"
        )
        self.update_model_status()

    def update_model_status(self, _event=None):
        if self.provider.get() != "LM Studio":
            return
        selected = next((m for m in self.model_catalogues["LM Studio"] if m["id"] == self.model.get()), None)
        if selected:
            state = (
                "ロード済み" if selected.get("state") == "loaded" else "未ロード（LM StudioのGUIで切り替えてください）"
            )
            self.context.set(
                f"モデル状態: {state} / Context Length: {selected.get('loaded_context_length') or '未設定'} tokens"
            )

    def update_search_state(self, _event=None):
        state = "normal" if self.search_backend.get() == SEARCH_LABELS["lmstudio"] else "disabled"
        self.embedding_box.configure(state=state)
        self.embedding_url_entry.configure(state=state)

    def settings(self):
        values = self.initial.model_dump()
        values.update(
            openai_api_base=self.base_url.get().strip(),
            openai_model=self.model.get().strip(),
            openai_api_key=self.api_key.get().strip(),
            tool_mode=self.tool_mode.get(),
            structured_mode=self.structured_mode.get(),
            max_subtasks=int(self.subtasks.get()),
            max_output_tokens=int(self.output_tokens.get()),
            search_backend="lmstudio" if self.search_backend.get() == SEARCH_LABELS["lmstudio"] else "tfidf",
            embedding_model=self.embedding_model.get().strip(),
            embedding_base_url=self.embedding_url.get().strip(),
            save_full_logs=bool(self.log_consent.get()),
            reasoning_effort="none" if self.provider.get() == "LM Studio" else None,
        )
        result = Settings(_env_file=None, **values)
        self.handler.formatter.secrets = [result.openai_api_key, result.embedding_api_key]
        return result

    def start(self, work, message="実行中…同じモデルを1件ずつ呼び出しています。"):
        if self.busy:
            return
        self.busy = True
        self.status.set(message)
        self.put(self.logs, "")
        for widget, _state in self.controls:
            widget.configure(state="disabled")
        self.question.configure(state="disabled")

        def worker():
            try:
                self.events.put(("done", work()))
            except Exception as exc:
                self.events.put(("error", public_error(exc, [self.api_key.get(), self.initial.embedding_api_key])))

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    def run(self, command):
        try:
            settings = self.settings()
            question = self.question.get("1.0", "end").strip()
            if command == "run":
                validate_question(question)
        except Exception as exc:
            messagebox.showerror("設定の確認", public_error(exc, [self.api_key.get()]))
            return
        self.put(self.answer, "実行中…")
        self.put(self.details, "")
        self.start(lambda: ("execution", execute(settings, command, question)))

    def get_models(self):
        try:
            settings = self.settings()
        except Exception as exc:
            messagebox.showerror("設定の確認", str(exc))
            return
        provider = self.provider.get()
        self.start(lambda: ("models", {"provider": provider, "items": list_models(settings)}), "モデル一覧を取得中…")

    def startup_models(self):
        if self.busy:
            return
        settings = self.initial.model_copy(
            update={
                "openai_api_base": self.initial.openai_api_base
                if self.provider.get() == "LM Studio"
                else "http://localhost:1234/v1",
            }
        )

        def fetch():
            try:
                return "models", {"provider": "LM Studio", "items": list_models(settings, timeout=3)}
            except Exception:
                return "startup_unavailable", None

        self.start(fetch, "起動時にLM Studioのモデル一覧を確認中…")

    def index(self):
        try:
            settings = self.settings()
        except Exception as exc:
            messagebox.showerror("設定の確認", str(exc))
            return
        self.start(
            lambda: ("index", prepare_index(settings)), "検索データを準備中…Embedding使用時は文書をベクトル化します。"
        )

    def poll(self):
        try:
            while True:
                event, value = self.events.get_nowait()
                if event == "log":
                    self.put(self.logs, value + "\n", append=True)
                    continue
                self.busy = False
                for widget, state in self.controls:
                    widget.configure(state=state)
                self.question.configure(state="normal")
                self.update_search_state()
                if event == "error":
                    self.status.set("停止しました。設定と経過ログを確認してください。")
                    self.put(self.answer, value)
                    continue
                kind, result = value
                if kind == "startup_unavailable":
                    self.status.set("準備完了。LM Studio起動後は「モデル一覧を更新」で取得できます。")
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
                    self.status.set(
                        f"{data['status']} / API {data['api_calls']}回 / {data['elapsed_seconds']}秒 / 保存先: {path}"
                    )
                    if data.get("local_model"):
                        self.context.set(
                            f"現在のロード済みContext Length: {data['local_model']['loaded_context_length']} tokens。変更はLM StudioのGUIで行います。"
                        )
                elif kind == "models":
                    provider, items = result["provider"], result["items"]
                    self.model_catalogues[provider] = items
                    chat_models = [m for m in items if m.get("type", "llm") != "embeddings"]
                    if provider == "LM Studio":
                        embedding_models = [m for m in items if m.get("type") == "embeddings"]
                        self.embedding_box.configure(values=[m["id"] for m in embedding_models])
                    if self.provider.get() == provider:
                        self.model_box.configure(values=[m["id"] for m in chat_models])
                        loaded = [m for m in chat_models if m.get("state") == "loaded"]
                        if (
                            provider == "LM Studio"
                            and len(loaded) == 1
                            and not any(m["id"] == self.model.get() for m in chat_models)
                        ):
                            self.model.set(loaded[0]["id"])
                        self.update_model_status()
                        self.status.set(
                            f"言語モデルを{len(chat_models)}件取得しました。未ロードのものはLM Studio側で切り替えてください。"
                        )
                    else:
                        self.status.set(
                            "LM Studioのモデル一覧を取得しました。接続先をLM Studioに切り替えると選択できます。"
                        )
                else:
                    self.status.set(f"検索データを準備しました: {result}")
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def close(self):
        if self.busy:
            messagebox.showinfo("実行中", "処理の完了を待ってから閉じてください。")
            return
        logging.getLogger().removeHandler(self.handler)
        self.handler.close()
        self.root.destroy()


def launch():
    ensure_runtime()
    configure_logging()
    root = tk.Tk()
    App(root)
    root.mainloop()
