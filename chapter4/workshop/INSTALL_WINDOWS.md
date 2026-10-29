# Windows導入ガイド（2026-10-29対策版）

Windows x64、RAM 16GB程度を想定しています。GPUとDockerは必須ではありません。インストールと基本質問1件は開催3日前までに済ませてください。

## 1. Pythonを用意する

[Python公式の3.14.10リリース](https://www.python.org/downloads/release/python-31410/)からWindows installer (64-bit)を入れ、Tcl/Tkを含めます。3.14.10以上の3.14系、同梱OpenSSL 3.5.9以上を使用してください。以前のPython・仮想環境は流用しません。アプリは古い実行環境を検出すると停止します。

仮想環境の名前は任意です。この手順は一般的な `.venv` を使います。すでに同名の古い環境がある場合は、別フォルダーへ新しくZIPを展開して準備してください。

ZIPをユーザーが書き込めるフォルダーに展開します。展開後の `chapter4` フォルダーで、エクスプローラーのアドレス欄に `powershell` と入力して開きます。

```powershell
py -3.14 --version
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -c "import sys,ssl; print(sys.version); print(ssl.OPENSSL_VERSION)"
```

`pip check` が `No broken requirements found.` と表示されれば依存関係の整合は通過です。仮想環境の有効化やPowerShellの実行ポリシー変更は不要です。requirementsはバージョン・ハッシュ・wheel形式を固定しています。ハッシュ不一致を無視するオプションは使わず、配布元のファイルを確認してください。

## 2. LM Studioを用意する

LM Studioで回答用の言語モデルを**1つだけ**ロードし、Developer画面でローカルサーバーを起動します。用途ごとに言語モデルを追加ロードする必要はありません。モデルの `Context Length` はLM StudioのGUIで調整し、必要ならロードし直します。アプリの「出力上限」は1回の生成量であり、コンテキスト長とは別です。

Embedding検索を使う場合は、検索用のEmbeddingモデルも1つロードします。確認に使ったのは言語モデル `qwen3.5-4b-abliterated-i1` とEmbedding `text-embedding-nomic-embed-text-v1.5` です。この名前に固定されてはいません。メモリが厳しければ検索方式にTF-IDFを選ぶとEmbeddingモデルは不要です。

## 3. 設定してGUIを開く

```powershell
Copy-Item .env.lmstudio.example .env
.\.venv\Scripts\python.exe -m workshop gui
```

次回からは `start-gui.cmd` のダブルクリックで起動できます。ランチャーは `.venv` → `venv` → `.venv-secure` の順に、必要なPython・ライブラリ・Tkinterを使える環境を探します。古いPythonの環境は飛ばします。名前自体を安全性の条件にはしていません。別の名前を使う場合は、その環境のPythonで `-m workshop gui` を実行してください。起動時と「モデル一覧を更新」でLM Studioのモデル一覧を取得します。未ロードのものも一覧に出るため、実行するモデルへLM Studio側で切り替えてください。API URLの標準値は `http://localhost:1234/v1`、ローカルのキー欄は `lm-studio` です。

1. 呼び出す言語モデルと検索方式を選ぶ。Embedding方式ならEmbeddingモデルも選ぶ。
2. 「検索データを準備」を押す。初回のEmbedding生成には時間がかかる。
3. 「接続・機能確認」を押す。接続・ツール・構造化出力の3項目を確認する。
4. 初期表示の二段階認証の質問を実行し、[質問例](QUESTIONS.md)の期待内容と照合する。

GUIの入力は `.env` に保存しません。次回の初期値を変更したい場合は `.env` を編集してください。本文保存のチェック欄は初期状態でオンです。`workshop/logs` に質問・回答・検索・評価の詳細と経過ログを保存します。共有前に内容を確認してください。保存したくない場合はチェックを外します。

## OpenRouterに切り替える場合

各自のキーを取得し `.env.openrouter.example` を `.env` にコピーしてキーを設定するか、GUIで接続先を切り替えて入力します。キーを主催者やチャットへ送らないでください。公式接続先 `https://openrouter.ai/api/v1` と末尾 `:free` の固定モデルIDだけを使います。設定例の無料モデルは実接続未確認の候補です。無料提供状況を確認し、開催前に担当Aが機能確認と基本質問を実行してください。無料枠や混雑で429になる場合があります。

## 困ったとき

| 症状 | 対処 |
|---|---|
| `py` がない、3.14が見つからない | Python公式インストーラーを確認。Python本体の絶対パスでもvenvを作成できる |
| 古いPython／OpenSSLで停止 | 古い仮想環境を別名で保管してから、更新したPythonで新規作成する |
| `No module named tkinter` | PythonのTcl/Tkコンポーネントを追加する |
| モデル一覧が空・通信失敗 | LM Studioのサーバー起動とポートを確認し、一覧を更新する |
| 選んだモデルが未ロード | LM Studioでそのモデルをロードして再度一覧を更新する |
| 言語モデルが複数ロード済み | LM Studioで使用しない言語モデルをアンロードする |
| Embedding未ロード／インデックス不一致 | 正しいEmbeddingモデルをロードし「検索データを準備」をやり直す |
| メモリ不足・遅い | TF-IDFへ変更、LM Studioのコンテキスト長・モデルサイズをPCに合わせて調整 |
| 形式エラー・ツール呼び出し失敗 | モデルの機能を確認。詳細ガイドの明示的なjson互換モードで切り分ける |
| 資料の整合性エラー | 配布ZIPの元データを使う。任意のPDFへ差し替える機能は今回の対象外 |
| OpenRouterの401／429 | キー・利用制限を確認し、連続再実行を控える |

別PCで初見導入するBの確認は別途必要です。A側では空の仮想環境へのハッシュ固定インストールを検証しています。
