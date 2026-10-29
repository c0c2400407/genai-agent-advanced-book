# 設定・実行の詳細（対策版）

初回導入は [Windows導入ガイド](INSTALL_WINDOWS.md)、確認状況は [STATUS.md](STATUS.md) を参照してください。以下は `chapter4` で実行します。標準環境はWindows x64 / Python 3.14.10以上の3.14系 / OpenSSL 3.5.9以上 / `.venv-secure` です。

## 仕組みとモデル

LangGraphで「質問の分解 → 検索ツールの選択 → 検索 → 回答 → 評価 → 必要なら再検索 → 最終回答」を実行します。計画・回答・評価は同じ言語モデルを使い、渡すメッセージを分けます。サブタスクは直列です。

LM Studioでは起動時と手動更新時にダウンロード済みのモデル一覧を取得し、言語モデルとEmbeddingモデルを分けて表示します。アプリからのモデルの自動ロード・再ロードはありません。実行前にロード状態を確認し、選択モデルが未ロード、または言語モデルが複数ロード済みなら停止します。コンテキスト長はLM StudioのGUIで設定し、現在のロード値をアプリに表示します。

検索方式はTF-IDF（文字2〜3グラム、検索用API不要）とLM Studio Embedding（ローカルAPI、コサイン類似度）の2つです。各検索ツールは上位3件を返します。対策版のpypdfでは配布資料からマニュアル43断片＋QA15件＝58件を生成します。旧版の62件と違うのはPDF抽出バージョンの変更によるものです。

## 設定例

`.env.lmstudio.example` または `.env.openrouter.example` を `.env` にコピーして編集します。GUIで入力した値はその画面だけで使用し、設定ファイルへ書き戻しません。

| 設定 | 用途 |
|---|---|
| `LLM_BASE_URL` | LM Studioのローカル `/v1` または公式OpenRouterの `/api/v1` |
| `LLM_MODEL` | 呼び出す言語モデル。OpenRouterは固定の `:free` ID必須 |
| `LLM_API_KEY` | OpenRouterは各自のキー。ローカルは `lm-studio` |
| `SEARCH_BACKEND` | `tfidf` または `lmstudio` |
| `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL` | ローカルEmbeddingの接続先とモデル |
| `EMBEDDING_BATCH_SIZE` | 文書のバッチサイズ。初期値8 |
| `EMBEDDING_DOCUMENT_PREFIX` / `EMBEDDING_QUERY_PREFIX` | `auto` はnomic v1.5へ文書 `search_document: `、検索語 `search_query: ` を付加。他モデルはモデルカードに従う |
| `MAX_SUBTASKS` | 1〜2。LM Studioの初期例は1 |
| `MAX_CHALLENGES` | 評価までの試行回数。初期値2、設定可能1〜3 |
| `MAX_API_CALLS` | 言語モデルの全体呼び出し上限。初期値20 |
| `MAX_OUTPUT_TOKENS` | 1回の生成出力上限。コンテキスト長とは別 |
| `REASONING_EFFORT` | 確認したQwenでは `none`。モデルにより対応が異なる |
| `SAVE_FULL_LOGS` | 初期値 `true`。質問・回答・検索結果・評価の詳細を保存。不要な場合は `false` |

Embeddingの文書・URL・モデル・プレフィックスを変えたら検索データを作り直します。`.workshop/documents.json` と `embeddings.json` は再生成可能なJSONです。pickleは使いません。資料は書籍付属の3ファイルをSHA256で確認してから解析します。任意のアップロードや外部URLの取得はありません。

## CLI

```powershell
.\.venv-secure\Scripts\python.exe -m workshop models
.\.venv-secure\Scripts\python.exe -m workshop status
.\.venv-secure\Scripts\python.exe -m workshop index
.\.venv-secure\Scripts\python.exe -m workshop preflight
.\.venv-secure\Scripts\python.exe -m workshop run "過去のQAを参照して、二段階認証で認証アプリを使う設定手順を教えてください。"
.\.venv-secure\Scripts\python.exe -m workshop search "二段階認証 認証アプリ"
```

`preflight` は接続・ネイティブツール・構造化出力を計3リクエストで確認します。`status` は生成APIを呼びません。終了コードは0が通過、2がモデル評価未完了または機能確認の一部失敗、1が設定・通信・形式等のエラーです。

標準は `native` ツールと `schema` 構造化出力です。対応が弱いモデルを切り分ける場合は、明示的に `--tool-mode json` や `--structured-mode json` を指定できます。JSONモードもPydanticで検証します。失敗時の自動切替はしません。`preflight` のツール項目は常にネイティブ機能を確認します。

## 保存と通信

回答や検索・評価の詳細はGUIで確認できます。**初期設定では後から調査できるよう、`workshop/logs/日時-run.json` に質問・計画・検索結果・評価・回答・実行設定を保存し、同名 `.log` に各段階の内容と経過を残します。** 途中で失敗した場合も、それまでの段階ログと質問、エラーの種類・発生位置を記録します。APIの生エラー本文や秘密値は保存しません。本文を保存しない場合はGUIの保存チェックを外すか `SAVE_FULL_LOGS=false` にします。その場合も状態・回数・所要時間・エラー等の診断情報は保存します。共有前にはログの内容を確認してください。キーはSecretStrとマスキングを使いますが、任意の個人情報を完全に匿名化する機能ではありません。

LM Studioへの通信はループバックのみ、OpenRouterは公式HTTPSだけに制限します。外部プロキシ環境変数とリダイレクトは使用しません。API応答のサイズ上限は8MiBです。アプリのグラフ実行ではLangSmithトレースを無効化します。OpenRouter使用時は質問と検索した資料が外部サービスへ送信されます。

## 呼び出し回数

1回で評価を通れば `2 + 3 × サブタスク数`、再試行上限まで使うと `2 + 3 × サブタスク数 × 試行回数` が目安です。初期2試行なら1タスク5〜8回、2タスク8〜14回です。SDKの自動再試行は無効、GUIとCLIの同時実行もロックします。Embedding生成・検索は別のローカルAPI回数として扱います。

OpenRouterは `:free` の固定IDと価格上限0を送信します。リクエスト間隔は最低3.2秒です。無料モデルの提供状況・利用制限は変わるため、[公式の制限説明](https://openrouter.ai/docs/api/reference/limits)を開催前に確認してください。設定例の候補は実接続未確認です。

## テストと配布

```powershell
.\.venv-secure\Scripts\python.exe -m unittest discover -s workshop -p "test_*.py"
.\.venv-secure\Scripts\python.exe -m workshop.package
```

外部生成APIを使わないテスト36件を通過しています。配布スクリプトは明示したコード・資料・設定例・確認記録だけを収録します。現在のAPIキー、`.env`、個人ログ、キャッシュ、実行環境は含めません。[監査結果](SECURITY_AUDIT.md)の確認範囲も参照してください。

主要コードの役割と勉強会での説明順は [CODE_GUIDE.md](CODE_GUIDE.md) を参照してください。
