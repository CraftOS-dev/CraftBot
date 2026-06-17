<div align="center">
    <img src="assets/README_banner.png" alt="CraftBot Banner" width="1280"/>
</div>

<div align="center">
    <img src="assets/craftbot_logo_text_small.png" alt="CraftBot" width="400"/>
</div>

ほとんどのエージェントハーネスは、チャットとツール呼び出しで止まります。CraftBotはその先へ進みます。自分自身のSaaSツールを構築し、進化させ、運用し、そのツールレイヤーを通じてあなたとコミュニケーションし、自動化を行います。

それに加えて、CraftBotは汎用エージェントハーネスとしてのコア機能をすべて備えています。リモート従業員のようにタスクを実行し、あなたの好みや目標を記憶し、あなたにとって大切なことを能動的に計画・実行する手助けをします。

<p align="center">
  <img src="https://img.shields.io/badge/OS-Windows-blue?logo=windows&logoColor=white" alt="Windows">
  <img src="https://img.shields.io/badge/OS-macOS-lightgrey?logo=apple&logoColor=white" alt="macOS">
  <img src="https://img.shields.io/badge/OS-Linux-yellow?logo=linux&logoColor=black" alt="Linux">


  <a href="https://github.com/CraftOS-dev/CraftBot">
    <img src="https://img.shields.io/github/stars/CraftOS-dev/CraftBot?style=social" alt="GitHub Repo stars">
  </a>

  <img src="https://img.shields.io/github/license/CraftOS-dev/CraftBot" alt="License">

  <a href="https://discord.gg/ZN9YHc37HG">
    <img src="https://img.shields.io/badge/Discord-Join%20the%20community-5865F2?logo=discord&logoColor=white" alt="Discord">
  </a>
</p>

<div align="center">
	
[![SPONSORED BY E2B FOR STARTUPS](https://img.shields.io/badge/SPONSORED%20BY-E2B%20FOR%20STARTUPS-ff8800?style=for-the-badge)](https://e2b.dev/startups)
</div>

<p align="center" style="display: inline-block">
<a href="https://www.producthunt.com/products/craftbot?embed=true&amp;utm_source=badge-top-post-badge&amp;utm_medium=badge&amp;utm_campaign=badge-craftbot" target="_blank" rel="noopener noreferrer" style="display: inline-block">
	<img alt="CraftBot - Self-hosted proactive AI assistant that lives locally | Product Hunt" width="250" height="54" src="https://api.producthunt.com/widgets/embed-image/v1/top-post-badge.svg?post_id=1110300&amp;theme=dark&amp;period=daily&amp;t=1776679679509">
</a>
<a href="https://theresanaiforthat.com/ai/craftbot/?ref=featured&v=10277523" target="_blank" rel="nofollow"><img width="265" src="https://media.theresanaiforthat.com/featured-on-taaft.png?width=600"></a>
</p>

<p align="center">
  <a href="README.md">English</a> | <a href="README.cn.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ko.md">한국어</a> | <a href="README.es.md">Español</a> | <a href="README.pt-BR.md">Português</a> | <a href="README.fr.md">Français</a> | <a href="README.de.md">Deutsch</a>
</p>

## ✨ 主な特徴

自前のSaaSツールを作って動かせるAIエージェントというだけでなく、CraftBotはエージェントハーネスのコア機能をひと通り備えており、あなたのタスク・ツール・記憶・日々のワークフローと一緒に動く汎用AIエージェントとして機能します。

- **Living UI.** CraftBotの中で動くカスタムアプリを構築・インポート・進化させられます。エージェントはUIの状態を常に把握し、そのデータを直接読み書き・操作できます。
- **マルチタスクとセッションルーティング.** まだ`/new`コマンドを叩いていますか？CraftBotは、いつ新しいセッションを始め、いつ既存のタスクを再開すべきかを自分で判断し、会話とコンテキストを一本化します。
- **セルフホスト & BYOK.** OpenAI、Google Gemini、Anthropic Claude、OpenRouterなどに対応する柔軟なLLMプロバイダーシステム。Ollamaを使えば、自分のモデルをトークン消費ゼロでホストすることも可能です。
- **メモリーシステム.** CraftBotとのやり取りから、RAG + エージェントファイルシステム + 蒸留によってローカルの知識ベースを構築。CraftBotは深夜に「夢を見て」、その日の出来事を統合します。
- **能動的なエージェント.** あなたの好み、習慣、人生の目標を学習。そのうえで計画を立て、タスクを起動(もちろん承認付きで)し、あなたの人生をより良くする手助けをします。
- **外部ツールとの連携.** Google Workspace、Slack、Notion、Zoom、LinkedIn、Discord、Telegramと接続可能(今後さらに追加予定)。認証情報の埋め込みやOAuthにも対応しています。
- **スキル & MCP.** 150以上のMCPと170以上のスキルが利用可能。新しいスキルやMCPもすぐに導入できます。完了したタスクからワンクリックでスキルを作成・改善することもできます。
- **クロスプラットフォーム.** Windows、macOS、Linuxを完全サポート。プラットフォーム別のコードバリアントとDockerコンテナ化を備えています。
- **ブラウザUIとCLIに対応.** あなたの使い方に合わせて選べます。日常使いには手軽なブラウザUIを、スクリプトやヘッドレス環境にはCLIをどうぞ。

---


## 🧰 はじめに

必要条件: Python 3.10+ ・ ブラウザモードを使う場合は Node.js 18+

```bash
# 1. リポジトリをクローン
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. インストール、自動起動の登録、CraftBotの起動
python craftbot.py install
```

これだけです。ターミナルは自動で閉じ、CraftBotはバックグラウンドで稼働し、ブラウザが自動で開きます。再度ブラウザを開けるように**デスクトップショートカット**も作成されます。

**インストール後のサービス管理:**

```bash
python craftbot.py start      # CraftBotをバックグラウンドで起動
python craftbot.py stop       # CraftBotを停止
python craftbot.py restart    # CraftBotを再起動
python craftbot.py status     # 実行状態と自動起動の有無を確認
python craftbot.py logs       # 最近のログ出力を表示
python craftbot.py uninstall  # 停止・自動起動の解除・パッケージのアンインストール
```

> [!TIP]
> `install`や`start`の後には、**CraftBotのデスクトップショートカット**が自動で作成されます。ブラウザを閉じてしまったら、このショートカットをダブルクリックするだけで再び開けます。

---

## 🌱 Living UI

**Living UIは、あなたのニーズに合わせて進化していくシステム/アプリ/ダッシュボードです。**

<div align="center">
    <img src="assets/living_ui_banner.gif" alt="CraftBot Banner" width="1280"/>
</div>

- AIコパイロット付きのカンバンボードが欲しい?
- 自分のワークフローにぴったり合うカスタムCRMは?
- CraftBotがあなたに代わって読み取り・操作できる社内ダッシュボードは?

```bash
# 1. リポジトリをクローン
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. conda環境にインストール
python install.py --conda

# 3. CraftBotを実行
conda run -n craftbot python run.py

# condaがPATHにない場合（Windowsのみ）：
&"$env:USERPROFILE\miniconda3\Scripts\conda.exe" run -n craftbot python run.py
```

> [!NOTE]
> CraftBotを実行するたびに `conda run -n craftbot python run.py` を使用してください。バックグラウンドサービスはありません — 自分で起動と停止を行います。

---

### オプション3 — 手動インストール（pip）

**これを選ぶなら：** Python環境を完全に自分で管理したい場合、自動サービスやバックグラウンドプロセスは不要な場合。

`install.py`（フラグなし）は現在アクティブなPython環境に標準pip installを実行します。`run.py` を使って手動でCraftBotを起動・停止します。

```bash
# 1. リポジトリをクローン
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. アクティブなPython環境に依存関係をインストール
python install.py

# 3. CraftBotを実行
python run.py
```

初回実行時にAPIキーと設定のセットアップがガイドされます。

> [!NOTE]
> Node.jsがインストールされていない場合、インストーラーがステップバイステップの手順を提供します。ブラウザモードを完全にスキップしてCLIモードを使用することもできます — Node.js不要：`python run.py --cli`

### インストール後にできること
- エージェントと自然言語で会話
- 複雑なマルチステップタスクの実行を依頼
- `/help` と入力して利用可能なコマンドを確認
- Google、Slack、Notionなどに接続

### 🖥️ インターフェースモード

<div align="center">
    <img src="assets/WCA_README_banner.png" alt="CraftOS Banner" width="1280"/>
</div>

CraftBotは複数のUIモードをサポートしています。お好みに応じて選択してください：

| モード | コマンド | 要件 | 最適な用途 |
|------|---------|--------------|----------|
| **ブラウザ** | `python run.py` | Node.js 18+ | モダンなWebインターフェース、最も使いやすい |
| **CLI** | `python run.py --cli` | なし | コマンドライン、軽量 |

**ブラウザモード**がデフォルトで推奨されます。Node.jsがない場合は、インストーラーがインストール手順を提供するか、代わりに**CLIモード**を使用できます。

---

## 🧬 Living UI

**Living UIは、あなたのニーズに合わせて進化するシステム/アプリ/ダッシュボードです。**

AIコパイロットが組み込まれたカンバンボードが必要ですか？あなたのワークフローに合わせて形作られたカスタムCRMは？
CraftBotが読み取って操作できる会社のダッシュボードは？
Living UIとして立ち上げれば、CraftBotと並んで動作し、あなたのニーズの変化に合わせて成長します。

<div align="center">
    <img src="assets/living-ui-example.png" alt="Living UI example" width="1280"/>
</div>

### Living UIを作る3つの方法

1. **ゼロから構築.** 欲しいものを自然な言葉で説明してください。CraftBotがデータモデル、バックエンドAPI、ReactのUIを足場として組み上げ、構造化された設計プロセスを通して一緒に改善していきます。

<div align="center">
    <img src="assets/living-ui-custom-build.png" alt="Building a Living UI from scratch" width="448"/>
</div>

2. **マーケットプレイスからインストール.** コミュニティが作ったLiving UIを[living-ui-marketplace](https://github.com/CraftOS-dev/living-ui-marketplace)から探せます。

<div align="center">
    <img src="assets/living-ui-marketplace.png" alt="Living UI marketplace" width="448"/>
</div>

3. **既存プロジェクトをインポート.** Go、Node.js、Python、Rust、または静的なソースコードやGitHubリポジトリをCraftBotに渡してください。ランタイムを検出し、ヘルスチェックを設定し、Living UIとしてラップします。

<div align="center">
    <img src="assets/living-ui-import.png" alt="Importing an existing project as a Living UI" width="448"/>
</div>

### CraftBotを内部に組み込んだまま進化し続ける

Living UIに「完成」はありません。ニーズが変われば、機能を追加したり、ビューをリデザインしたり、新しいデータと連携させたり、エージェントに頼んでください。

CraftBotはすべてのLiving UIに組み込まれており、**状態を常に把握**しています。現在のDOMやフォーム値を読み取り、REST API経由でアプリのデータを参照し、あなたに代わってアクションを起こせます。

### SaaSツールをオープンに、生き続けるものへ

自分専用のLiving UIを構築・カスタマイズ・進化させ、自分の用途に完璧には合わないサブスクリプションツールへの依存を減らしていきましょう。

私たちはLiving UIを公開してくれる開発者を積極的に探しており、**[Living UIマーケットプレイス](https://craftos.net/marketplace)**にエクスポートできます。PRも大歓迎です!

---
 
# 5分で試せる3つのLiving UI
 
- **📋 カンバンボード** — タスク、フォローアップ、CTAをすべて一か所に。CraftBotが操作してPM業務を肩代わりできます。
- **📊 習慣トラッカー** — 習慣を作り、追跡する。開発者がコミットを刻むように、GitHub風のアクティビティカレンダーで習慣を可視化。
- **🐦 Luolinglo** — Duolingoではないですが、新しい言語を学び、フラッシュカードを作り、CraftBotと一緒に練習できます。

## 🧩 アーキテクチャの概要

| コンポーネント | 説明 |
|-----------|-------------|
| **エージェントベース** | タスクライフサイクルを管理し、コンポーネント間を調整し、メインのエージェントループを処理するコアオーケストレーションレイヤー。 |
| **LLMインターフェース** | 複数のLLMプロバイダー（OpenAI、Gemini、Anthropic、BytePlus、Ollama）をサポートする統一インターフェース。 |
| **コンテキストエンジン** | KVキャッシュサポートで最適化されたプロンプトを生成。 |
| **アクションマネージャー** | ライブラリからアクションを取得して実行。カスタムアクションの拡張が容易。 |
| **アクションルーター** | タスク要件に基づいて最適なアクションをインテリジェントに選択し、必要に応じてLLMを介して入力パラメータを解決。 |
| **イベントストリーム** | タスク進行状況の追跡、UI更新、実行モニタリング用のリアルタイムイベント発行システム。 |
| **メモリマネージャー** | ChromaDBを使用したRAGベースのセマンティックメモリ。メモリのチャンキング、埋め込み、検索、増分更新を処理。 |
| **ステートマネージャー** | エージェント実行コンテキスト、会話履歴、ランタイム設定を追跡するグローバルステート管理。 |
| **タスクマネージャー** | タスク定義を管理し、シンプルタスクと複雑タスクモードの切り替え、TODO作成、マルチステップワークフロー追跡を可能にします。 |
| **スキルマネージャー** | エージェントコンテキストにプラグイン可能なスキルをロードして注入。 |
| **MCPアダプター** | MCPツールをネイティブアクションに変換するModel Context Protocol統合。 |

---

## 🔜 ロードマップ

- [X] **メモリモジュール** — 完了。
- [ ] **外部ツール統合** — さらに追加中！
- [X] **MCPレイヤー** — 完了。
- [X] **スキルレイヤー** — 完了。
- [ ] **プロアクティブな動作** — 実装予定

---

## 📋 コマンドリファレンス

### install.py

| フラグ | 説明 |
|------|-------------|
| `--conda` | conda環境を使用（オプション） |

### run.py

| フラグ | 説明 |
|------|-------------|
| (なし) | **ブラウザ**モードで実行（推奨、Node.jsが必要） |
| `--cli` | **CLI**モードで実行（軽量） |

**インストール例:**
```bash
# シンプルなpipインストール（condaなし）
python install.py

# conda環境を使用（condaユーザー向け推奨）
python install.py --conda
```

**CraftBotの実行:**

```powershell
# ブラウザモード（デフォルト、Node.jsが必要）
python run.py

# CLIモード（軽量）
python run.py --cli

# conda環境で
conda run -n craftbot python run.py

# condaがPATHにない場合はフルパスを使用
&"$env:USERPROFILE\miniconda3\Scripts\conda.exe" run -n craftbot python run.py
```

**Linux/macOS (Bash):**
```bash
# ブラウザモード（デフォルト、Node.jsが必要）
python run.py

# CLIモード（軽量）
python run.py --cli

# conda環境で
conda run -n craftbot python run.py
```

### 🔧 バックグラウンドサービス（推奨）

ターミナルを閉じても CraftBot が動き続けるようにバックグラウンドサービスとして実行します。デスクトップショートカットが自動作成されるので、いつでもブラウザを再度開けます。

```bash
# 依存関係インストール、ログイン時自動起動の登録、CraftBot の起動
python craftbot.py install
```

以上です。ターミナルは自動で閉じ、CraftBot はバックグラウンドで動作し、ブラウザが自動で開きます。

```bash
# その他のサービスコマンド:
python craftbot.py start    # CraftBot をバックグラウンドで起動
python craftbot.py status   # 実行中かどうか確認
python craftbot.py stop     # CraftBot を停止
python craftbot.py restart  # CraftBot を再起動
python craftbot.py logs     # 最近のログ出力を確認
```

| コマンド | 説明 |
|---------|-------------|
| `python craftbot.py install` | 依存関係インストール、ログイン時自動起動の登録、CraftBot 起動、ブラウザを開き、ターミナルを自動で閉じる |
| `python craftbot.py start` | CraftBot をバックグラウンドで起動（すでに実行中の場合は自動再起動、ターミナルは自動で閉じる） |
| `python craftbot.py stop` | CraftBot を停止 |
| `python craftbot.py restart` | CraftBot を停止して再起動 |
| `python craftbot.py status` | CraftBot が実行中か、自動起動が有効かを確認 |
| `python craftbot.py logs` | 最近のログ出力を表示（`-n 100` でより多く表示） |
| `python craftbot.py uninstall` | CraftBot を停止、自動起動の登録解除、pip パッケージのアンインストール、pip キャッシュの削除 |

> [!TIP]
> `craftbot.py start` または `craftbot.py install` の後、**CraftBot デスクトップショートカット**が自動作成されます。ブラウザを誤って閉じた場合は、ショートカットをダブルクリックして再度開けます。

> [!NOTE]
> **インストール:** インストーラーは依存関係が不足している場合、明確なガイダンスを提供します。Node.jsが見つからない場合は、インストールを促すか、CLIモードに切り替えることができます。インストールはGPUの可用性を自動検出し、必要に応じてCPU専用モードにフォールバックします。

> [!TIP]
> **初回セットアップ:** CraftBotはAPIキー、エージェントの名前、MCP、スキルを設定するオンボーディングシーケンスをガイドします。

> [!NOTE]
> **Playwright Chromium:** WhatsApp Web連携にはオプションです。インストールに失敗しても、エージェントは他のタスクでは問題なく動作します。後で手動でインストールできます: `playwright install chromium`

---

## 🔧 トラブルシューティングとよくある問題

### Node.jsが見つからない (ブラウザモード)
`python run.py`を実行したときに **「npm not found in PATH」** と表示された場合:
1. [nodejs.org](https://nodejs.org/)からLTS版をダウンロード
2. インストール後、ターミナルを再起動
3. もう一度`python run.py`を実行

**代替手段:** 代わりにCLIモードを使用（Node.js不要）：
```bash
python run.py --cli
```

### 依存関係のせいでインストールに失敗する
インストーラーは詳細なエラーメッセージと対処法を表示するようになりました。失敗した場合:
- **Pythonのバージョンを確認:** Python 3.10以上か確認(`python --version`)
- **インターネット接続を確認:** インストール中に依存関係をダウンロードします
- **pipキャッシュをクリア:** `pip install --upgrade pip`を実行してからやり直す

### Playwrightのインストールに失敗する
Playwright Chromiumのインストールは任意です。失敗しても:
- 他のタスクではエージェントは**問題なく動作**します
- スキップして、あとから`playwright install chromium`でインストール可能
- WhatsApp Web連携を使う場合にのみ必要です

詳しいトラブルシューティングは [INSTALLATION_FIX.md](INSTALLATION_FIX.md) を参照してください。

---
## 🐳 コンテナで実行する

リポジトリのルートには、Python 3.10、主要なシステムパッケージ(OCR用のTesseractを含む)、そして`environment.yml`/`requirements.txt`で定義されたすべてのPython依存関係を含むDocker構成が用意されており、隔離された環境でもエージェントを一貫して動かせます。

以下は、コンテナでエージェントを動かすための手順です。

### イメージをビルドする

リポジトリのルートから:

```bash
docker build -t craftbot .
```

### コンテナを実行する

イメージは既定で`python -m app.main`を起動するように設定されています。インタラクティブに動かす場合:

```bash
docker run --rm -it craftbot
```

環境変数が必要な場合は、envファイルを渡してください(例として`.env.example`を元に作成):

```bash
docker run --rm -it --env-file .env craftbot
```

コンテナ外に永続化したいディレクトリ(データやキャッシュなど)は`-v`でマウントし、ポートやその他のフラグもデプロイ要件に応じて調整してください。コンテナにはOCR用(`tesseract`)や一般的なHTTPクライアントなどのシステム依存が同梱されているので、ファイル操作やネットワークAPIをコンテナ内でそのまま扱えます。

既定ではPython 3.10を使い、`environment.yml`/`requirements.txt`のPython依存関係を取り込んでいるので、`python -m app.main`がすぐに動きます。

---

## 🤝 コントリビュート方法

PR歓迎です! ワークフロー(フォーク → `dev`からブランチを切る → PR)については[CONTRIBUTING.md](CONTRIBUTING.md)をご覧ください。すべてのプルリクエストはリント + スモークテストCIを自動で通過します。

> [!IMPORTANT]
> **CraftBot**は毎週改善が入る、活発に開発中のプロジェクトです。質問や素早いやり取りがしたい場合は、[Discord](https://discord.gg/ZN9YHc37HG)に参加するか、thamyikfoong(at)craftos.net までメールしてください。

---

## 🧾 ライセンス

このプロジェクトは [MITライセンス](LICENSE) の下で公開されています。自由に利用・ホスト・収益化していただけます(配布や収益化を行う場合は、本プロジェクトのクレジット表記が必要です)。

---

## ⭐ 謝辞

[CraftOS](https://craftos.net/) とコントリビューターによって開発・メンテナンスされています。
**CraftBot** が役に立ったら、ぜひリポジトリに⭐を付けて、他の人にもシェアしてください!

---

## スター履歴

<a href="https://www.star-history.com/?repos=CraftOS-dev%2FCraftBot&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
 </picture>
</a>
