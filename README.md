# 第4章 ヘルプデスクAIエージェント 勉強会・対策版

LM Studio／OpenRouterに対応したGUI・CLIを用意しています。2026-10-29の対策版ではPythonと依存関係を更新し、通信・入力・ログ保存・配布内容を見直しました。

**[Windows導入ガイド](chapter4/workshop/INSTALL_WINDOWS.md) → [第4章README](chapter4/README.md)** の順に確認してください。Python 3.14.10以上の3.14系、専用の `.venv` を使います。古いPythonで作った仮想環境は流用せず、新しく作成してください。セキュリティのためです。

依存46パッケージのOSV照合は既知の該当0件、自動テストは40件通過です。[監査と対策の詳細](chapter4/workshop/SECURITY_AUDIT.md)、[動作確認と未確認事項](chapter4/workshop/STATUS.md)も収録しています。OpenRouterの実接続は未確認です。

リポジトリ直下のrequirements.txtも対策版のハッシュ固定requirementsを参照します。他章の環境は今回の更新対象ではありません。

配布物：[勉強会用ZIP](chapter4/dist/helpdesk-workshop-secure-20261029.zip) ／ [SHA256](chapter4/dist/helpdesk-workshop-secure-20261029.zip.sha256)

## 書籍リポジトリの案内

<img src=".github/assets/cover.jpg" alt="書籍カバー" width="300">

[「現場で活用するためのAIエージェント実践入門」（講談社）](www.amazon.co.jp/dp/4065401402)のリポジトリです。

本リポジトリでは、書籍のうち実装に関する章を中心に、各章のコードや設定ファイルを提供しています。

## 本リポジトリの使用方法

本リポジトリではVSCodeを使用した実行を想定しています。

各章で独立した管理を行うためにVSCodeのMulti-root workspaces（以降ワークスペース）を活用します。
   
ワークスペースでの作業は以下のいずれかの方法で行います。
- Finderやエクスプローラーで本リポジトリ内の`genai-book.code-workspace`ファイルをダブルクリックしてVSCodeを起動する
- VSCodeのメニューから`ファイル > ファイルでワークスペースを開く`を選択し、`genai-book.code-workspace`ファイルを選択する

各章のコードは、`chapter<章番号>`ディレクトリに格納されており、ワークスペースとして個別に開くことができます。
実行する際はそれぞれの章のREADME.mdを参照し、環境構築や実行方法を確認してください。特に**Pythonの仮想環境はそれぞれの章のワークスペース内に作成することを想定しているのでご注意ください。**

## サポート
- 疑問点や不具合の報告はGitHubのIssuesで受け付けています。不明な点などがございましたら、[issues](https://github.com/masamasa59/genai-agent-advanced-book/issues)をご覧ください。
- 書籍の誤植（修正対応済み）は、[誤植一覧 (Closed)](https://github.com/masamasa59/genai-agent-advanced-book/issues?q=state%3Aclosed%20label%3A%E8%AA%A4%E6%A4%8D)にまとめています。修正対応前の誤植は[誤植一覧 (Open)](https://github.com/masamasa59/genai-agent-advanced-book/issues?q=state%3Aopen%20label%3A%E8%AA%A4%E6%A4%8D)にあります。あわせてご参照ください。
