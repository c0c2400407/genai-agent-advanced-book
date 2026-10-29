# 出典と変更点

基にしたコードは [c0c2400407/genai-agent-advanced-book](https://github.com/c0c2400407/genai-agent-advanced-book) の第4章です。取得時のコミットは `50a6536cf632ff810a6e61074af78d9a02da2ddc`、元の著者リポジトリは [masamasa59/genai-agent-advanced-book](https://github.com/masamasa59/genai-agent-advanced-book) です。

本の `src/agent.py` のLangGraph、Plan・ReflectionResultなどのデータ型、基本のプロンプトを利用しています。変更は以下です。

- LLM呼び出しを `src/llm.py` に集め、設定したOpenRouterまたはLM Studioへ送信。
- OpenRouterは固定無料IDのみ許可。価格上限を0にし、自動ルーターや有料モデルへの切替を使わない。
- 本のOpenAI埋め込みAPIとElasticsearch・Qdrantの検索を、勉強会では `workshop/search.py` のローカルTF-IDFまたはLM Studio Embeddingによるベクトル検索へ置換。
- 1モデルを使ってサブタスクを直列実行。計画、各サブタスク、最終回答にはそれぞれ必要なメッセージを渡す。
- 再検索時に過去のツール呼び出しとツール応答を両方除き、APIに不整合な会話履歴を送らないよう修正。
- 構造化出力とツール選択に明示的な互換モードを追加。回数上限、出典、実行結果の記録を追加。

CLIはLM Studioの[OpenAI互換API](https://lmstudio.ai/docs/developer/openai-compat)、[ツール](https://lmstudio.ai/docs/developer/openai-compat/tools)、[構造化出力](https://lmstudio.ai/docs/developer/openai-compat/structured-output)を使用します。OpenRouterの機能・価格指定は[Provider Routing](https://openrouter.ai/docs/guides/routing/provider-selection)を参照しています。

配布ZIPは勉強会に必要なコードと書籍付属のPDF・QAデータを収録します。元リポジトリのライセンスを追加・変更するものではありません。

Embeddingは [LM Studioの互換API](https://lmstudio.ai/docs/developer/openai-compat/embeddings) を使用します。nomicのプレフィックスは [モデルカード](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5) に従っています。

対策版ではLangGraph 1.2.18、langchain-core 1.7.1、pypdf 6.21.4へ更新し、外部トレース無効化、通信境界、入力検証、本文ログの保存切り替え、ハッシュ固定導入を追加しています。詳細は [SECURITY_AUDIT.md](SECURITY_AUDIT.md) を参照してください。

構造整理では `agent.py` をグラフの順序・分岐に絞り、各処理を `steps.py`、実行ログの保存を `workshop/run_log.py` へ分離しました。重複したAPI例外処理は共通境界へ集め、モジュールの読み込み時にルートロガーを書き換える副作用をなくしています。入出力形式・設定・既定の詳細ログ保存・再試行上限は引き継いでいます。
