# 第4章 ヘルプデスクAIエージェント 勉強会・対策版

2026-10-29版。LM StudioとOpenRouterに対応したWindows向けGUI／CLIです。「質問の分解 → 検索 → 回答 → 評価・再試行 → 最終回答」を確認できます。

**最初は [Windows導入ガイド](workshop/INSTALL_WINDOWS.md) の手順で準備してください。** Python 3.14.10以上の3.14系（Tcl/Tkを含む、OpenSSL 3.5.9以上）が必要です。古いPythonで作った環境を流用せず、仮想環境を新しく作ります。Dockerは今回使いません。

```powershell
# ZIPを展開し、chapter4フォルダーで実行
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
Copy-Item .env.lmstudio.example .env
.\.venv\Scripts\python.exe -m workshop gui
```

GUI起動後は呼び出す言語モデルと検索方式を選び、「検索データを準備」「接続・機能確認」「質問を実行」の順に操作します。LM Studio側で言語モデルを1つだけロードしてください。Embedding検索を使う場合は、別途Embeddingモデルを1つロードして選択します。アプリはモデルの自動ロードを行いません。コンテキスト長はLM StudioのGUIで設定します。

- [主要コードの読み方](workshop/CODE_GUIDE.md)
- [詳しい設定とCLI](workshop/README.md)
- [質問例と期待する回答](workshop/QUESTIONS.md)
- [確認結果・未確認事項](workshop/STATUS.md)
- [監査・対策結果](workshop/SECURITY_AUDIT.md)
- [出典と変更点](workshop/SOURCE.md)

依存関係は `requirements.txt` → `workshop/requirements.lock.txt` で全件のバージョンとSHA256を固定しています。Windows x64用です。設定例以外の `.env`、APIキー、仮想環境はZIPに含めません。質問・回答・検索結果の本文保存は初期設定で有効です。不要な場合はGUIの保存チェックを外すか `SAVE_FULL_LOGS=false` にします。

OpenRouterは末尾 `:free` の固定モデルIDを指定します。OpenRouterの `nvidia/nemotron-3.5-super-vl:free` で、nativeツール・schema構造化出力・TF-IDF検索による基本質問の実行に成功しました（API 5回、26.47秒、評価OK）。 成功した設定を `.env.openrouter.example` に反映しています。提供状況は開催前にも確認してください。

リポジトリ内に残る元の `src/tools`・`src/scripts`、Docker手順はこの配布版の対象外です。通常の導入は上記pip手順を使います。開発者向け `pyproject.toml`・`uv.lock` も対策後の直接依存に更新しています。
