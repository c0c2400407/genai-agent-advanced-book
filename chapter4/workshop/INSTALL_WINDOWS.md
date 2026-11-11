# Windows導入ガイド（2026-10-29対策版）

Windows x64、RAM 16GB程度を想定しています。GPUとDockerは必須ではありません。インストールと基本質問1件は開催3日前までに済ませてください。

**勉強会ではLM Studioを標準の接続先として推奨します。** OpenRouterの無料モデルは日次・分単位のリクエスト上限があり、このエージェントは質問1件で複数回呼び出すため、試行中に無料枠を使い切ることがあります。ローカルで動かせるモデルを選べる場合は、LM Studioを使ってください。

## 1. Pythonを用意する

[Python公式の3.14.10リリース](https://www.python.org/downloads/release/python-31410/)からWindows installer (64-bit)を入れます。3.14.10以上の3.14系、同梱OpenSSL 3.5.9以上を使用してください。以前のPython・仮想環境は流用しません。アプリは古い実行環境を検出すると停止します。GUIはPySide6を使います。

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

LM Studioに回答用の言語モデルをダウンロードし、Developer画面でローカルサーバーを起動します。質問実行時にアプリが選択モデルを自動ロードし、別の言語モデルがロード済みなら切り替えます（LM Studio 0.4.0以降）。Embedding検索を使う場合はEmbeddingモデルをロードしてください。モデルの `Context Length` を個別に調整したい場合は、LM Studioで設定したモデルをロード済みにしてから実行します。アプリの「出力上限」は1回の生成量であり、コンテキスト長とは別です。

Embedding検索を使う場合は、検索用のEmbeddingモデルも1つロードします。確認に使ったのは言語モデル `qwen3.5-4b-abliterated-i1` とEmbedding `text-embedding-nomic-embed-text-v1.5` です。この名前に固定されてはいません。メモリが厳しければ検索方式にTF-IDFを選ぶとEmbeddingモデルは不要です。

## 3. 設定してGUIを開く

```powershell
Copy-Item .env.lmstudio.example .env
.\.venv\Scripts\python.exe -m workshop gui
```

このコマンドは `chapter4` フォルダーを現在の作業場所にして実行してください。リポジトリ直下からPowerShellを開いた場合は、先に `Set-Location .\chapter4` を実行します。`workshop\gui.py` や `workshop\__main__.py` を直接実行する方法では、兄弟フォルダーの `src` を読み込めず起動しません。

次回からは `start-gui.cmd` のダブルクリックで起動できます。ランチャーは `.venv` → `venv` → `.venv-secure` の順に、必要なPython・ライブラリ・PySide6を使える環境を探します。古いPythonの環境は飛ばします。名前自体を安全性の条件にはしていません。別の名前を使う場合は、その環境のPythonで `-m workshop gui` を実行してください。起動時と「モデル一覧を更新」でLM Studioのモデル一覧を取得します。API URLの標準値は `http://localhost:1234/v1`、ローカルのキー欄は `lm-studio` です。質問実行時に未ロードの選択モデルを自動ロードします。

モデル一覧の取得には、アプリを実行するPythonからLM StudioのローカルAPI `http://127.0.0.1:1234/api/v0/models` へ接続できる必要があります。Codexなどの制限された実行環境・コンテナ・リモート環境では、PC上のLM Studioへの接続を環境側が拒否する場合があります。その場合は設定を変えず、Windowsデスクトップ上の通常のPowerShellまたは `start-gui.cmd` から起動してください。Windows Defender ファイアウォールの許可が表示された場合は、使用中のPython実行ファイルについてプライベートネットワークの通信を許可します。ファイアウォール全体を無効にしないでください。

通信確認は `chapter4` フォルダーで次のコマンドを実行します。

```powershell
.\.venv\Scripts\python.exe -m workshop models
```

モデルIDが表示されれば通信できています。GUIの「経過ログ」に `MODEL_LIST_RESPONSE ... http_status=200` と `MODEL_LIST_REQUEST ... status=success count=...` が出ることも確認してください。`PermissionError` または `ConnectError` の場合は、LM StudioのDeveloper画面でローカルサーバーが起動中か、アプリを実行している環境からlocalhostへの通信が許可されているか確認します。

1. 呼び出す言語モデルと検索方式を選ぶ。Embedding方式ならEmbeddingモデルもロードして選ぶ。
2. 「検索データを準備」を押す。初回のEmbedding生成には時間がかかる。
3. 接続・機能確認を使う場合は、先に選択モデルをLM Studioでロードする。この確認ボタンは自動ロードしない。
4. 初期表示の質問を実行する。未ロードの呼び出しモデルは実行時に自動ロードされます。[質問例](QUESTIONS.md)の期待内容と照合する。

GUIの入力は `.env` に保存しません。次回の初期値を変更したい場合は `.env` を編集してください。本文保存のチェック欄は初期状態でオンです。`workshop/logs` に質問・回答・検索・評価の詳細と経過ログを保存します。共有前に内容を確認してください。保存したくない場合はチェックを外します。

## OpenRouterに切り替える場合

OpenRouterはLM Studioを使えない場合の代替です。各自のキーを取得し `.env.openrouter.example` を `.env` にコピーして設定するか、GUIで入力します。キーを主催者やチャットへ送らないでください。公式接続先 `https://openrouter.ai/api/v1` と末尾 `:free` の固定モデルIDを使います。

OpenRouterの公式説明では、無料モデルは現在20リクエスト/分・50リクエスト/日が上限で、失敗した生成リクエストも日次枠に数えられます。アプリは設定にもよりますが質問1件につき5〜14回程度モデルを呼ぶため、上限に早く達することがあります。上限は変更されるため、利用前に[公式の無料モデル制限](https://openrouter.ai/collections/free-models/)を確認してください。以前の成功実績は現在の提供状況を保証しません。HTTP 401はキーの認証失敗、429は利用制限を示します。

## 困ったとき

| 症状 | 対処 |
|---|---|
| `py` がない、3.14が見つからない | Python公式インストーラーを確認。Python本体の絶対パスでもvenvを作成できる |
| 古いPython／OpenSSLで停止 | 古い仮想環境を別名で保管してから、更新したPythonで新規作成する |
| `No module named PySide6` | `requirements.txt` から依存関係を再インストールする |
| モデル一覧が空・通信失敗 | LM Studioのサーバーを起動し、上記の通信確認を実行する。`PermissionError` / `ConnectError` は制限された実行環境から通常のWindowsデスクトップ起動へ切り替える |
| 自動ロードがHTTP 404 | LM Studioを0.4.0以降に更新してAPIサーバーを再起動する |
| 自動ロードがHTTP 401/403 | LM Studio API認証を有効にしている場合は、APIトークンをローカルのキー欄へ入力する |
| 選んだモデルが一覧にない | LM Studioでモデルをダウンロードし、アプリのモデル一覧を更新する |
| Embedding未ロード／インデックス不一致 | 正しいEmbeddingモデルをロードし「検索データを準備」をやり直す |
| メモリ不足・遅い | TF-IDFへ変更、LM Studioのコンテキスト長・モデルサイズをPCに合わせて調整 |
| 形式エラー・ツール呼び出し失敗 | モデルの機能を確認。詳細ガイドの明示的なjson互換モードで切り分ける |
| 資料の整合性エラー | 配布ZIPの元データを使う。任意のPDFへ差し替える機能は今回の対象外 |
| OpenRouterでschema非対応と表示 | 構造化出力をjsonへ変更するか、schema対応の無料モデルを選ぶ。設定の自動変更はしない |
| OpenRouterの404 | 対応機能、配信先の稼働、プライバシー設定を確認する。モデル一覧への掲載だけでは利用可能とは限らない |
| OpenRouterの401／429 | キー・利用制限を確認し、連続再実行を控える |

別PCで初見導入するBの確認は別途必要です。A側では空の仮想環境へのハッシュ固定インストールを検証しています。
