# AIエージェント実践入門 第3章

本プロジェクトは「AIエージェント実践入門」第3章のサンプルコードを実行するための環境です。LLM呼び出しはLM StudioのローカルOpenAI互換サーバーを使用します。

## 前提条件

- Python 3.12 以上
- VS Code
- LM Studioと、LM Studioでロード可能なチャットモデル
- DockerおよびDocker Compose（PostgreSQLの例を動かす場合）
- TavilyのAPIキー（Web検索の例を動かす場合のみ）

依存関係は `pyproject.toml` に記載されています。

## 環境構築

### 1. chapter3のワークスペースを開く

VS Codeでchapter3のフォルダーを開き、ターミナルもchapter3ディレクトリにします。

### 2. uvのインストール

`uv`がまだない場合は、以下でインストールします。

```bash
pip install uv
```

### 3. Python依存関係のインストール

```bash
uv sync --extra dev
```

### 4. VS Codeのノートブックカーネルを選択

`chapter3/.venv/Scripts/python.exe` をPython環境として選択します。`chapter3/notebooks/examples.ipynb` を開き、右上のカーネル選択からこの環境を選び、カーネルを再起動してください。

### 5. LM Studioのサーバーを設定

1. LM Studioでチャットモデルをダウンロードし、ロードします。
2. **Developer**タブでローカルサーバーを起動します。既定のアドレスは `http://localhost:1234` です。
3. `chapter3/.env.example` を `chapter3/.env` にコピーします。既定のOpenAI互換API URLは `http://127.0.0.1:1234/v1` です。
4. `LMSTUDIO_MODEL`を空欄にすると、サーバーから見える最初のモデルを自動選択します。モデルを明示する場合は、`http://127.0.0.1:1234/v1/models`で返るIDを設定してください。
5. LM Studio側で認証を有効にしていなければ、`LMSTUDIO_API_KEY=lm-studio`のままで構いません。認証を有効にした場合は、発行したトークンを `.env` に設定します。

ノートブックの最初のAPIセルを実行する前に、LM Studioのサーバーが起動し、モデルがロードされている必要があります。関数呼び出しと構造化出力の例は、対応するモデルを選んでください。モデルによってはこれらの機能に対応しません。

Web検索の例を使う場合だけ `TAVILY_API_KEY` を設定します。SQL検索の例にはPostgreSQLのセットアップも必要です（`setup_postgres.sh`を参照）。

