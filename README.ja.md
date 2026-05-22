
<div align="center">
    <img src="assets/craftbot_readme_banner.png" alt="CraftBot Banner" width="1280"/>
</div>
<br>

<div align="center">
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
<br/>
<br/>

[![SPONSORED BY E2B FOR STARTUPS](https://img.shields.io/badge/SPONSORED%20BY-E2B%20FOR%20STARTUPS-ff8800?style=for-the-badge)](https://e2b.dev/startups)

<a href="https://www.producthunt.com/products/craftbot?embed=true&amp;utm_source=badge-top-post-badge&amp;utm_medium=badge&amp;utm_campaign=badge-craftbot" target="_blank" rel="noopener noreferrer"><img alt="CraftBot - Self-hosted proactive AI assistant that lives locally | Product Hunt" width="250" height="54" src="https://api.producthunt.com/widgets/embed-image/v1/top-post-badge.svg?post_id=1110300&amp;theme=dark&amp;period=daily&amp;t=1776679679509"></a>
</div>

<p align="center">
  <a href="README.md">English</a> | <a href="README.cn.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ko.md">한국어</a> | <a href="README.es.md">Español</a> | <a href="README.pt-BR.md">Português</a> | <a href="README.fr.md">Français</a> | <a href="README.de.md">Deutsch</a>
</p>

## 🚀 概要
<h3 align="center">
CraftBotは、あなたのマシンに常駐し、24時間365日働くパーソナルAIアシスタントです。
</h3>

タスクを自律的に解釈し、アクションを計画し、目標を達成するために実行します。
あなたの好みや目的を学習し、人生の目標を達成するためのタスクを積極的に計画・開始します。
MCP、スキル、外部アプリとの連携をサポートしています。

CraftBotはあなたの命令を待っています。今すぐあなた専用のCraftBotをセットアップしましょう。

<div align="center">
    <img src="assets/craftbot_overview.png" alt="CraftBot Overview" width="1280"/>
</div>

---

## ✨ 特徴

- **Bring Your Own Key (BYOK)** — OpenAI、Google Gemini、Anthropic Claude、BytePlus、ローカルOllamaモデルをサポートする柔軟なLLMプロバイダーシステム。プロバイダー間の切り替えが簡単です。
- **メモリシステム** — 一日を通して起きたイベントを深夜に整理・統合します。
- **プロアクティブエージェント** — あなたの好み、習慣、人生の目標を学習し、計画を立て、タスクを開始して（もちろん承認付きで）あなたの生活をより良くします。
- **Living UI** — CraftBotの中で動作するカスタムアプリを構築、インポート、または進化させます。エージェントはUIの状態を常に把握し、そのデータを直接読み取り、書き込み、操作できます。
- **外部ツール統合** — 埋め込みクレデンシャルとOAuthサポートにより、Google Workspace、Slack、Notion、Zoom、LinkedIn、Discord、Telegramに接続（今後さらに追加予定！）。
- **MCP** — 外部ツールやサービスでエージェント機能を拡張するためのModel Context Protocol統合。
- **スキル** — タスク計画、リサーチ、コードレビュー、Git操作などの組み込みスキルを含む拡張可能なスキルフレームワーク。
- **クロスプラットフォーム** — プラットフォーム固有のコードバリアントとDockerコンテナ化によるWindows、macOS、Linuxの完全サポート。

> [!IMPORTANT]
> **GUIモードは非推奨になりました。** CraftBotはGUI（デスクトップ自動化）モードをサポートしなくなりました。代わりにBrowserまたはCLIモードをご利用ください。

<div align="center">
    <img src="assets/craftbot_readme_features.png" alt="CraftBot Banner" width="1280"/>
	<img src="assets/craftbot_features_custom.png" alt="CraftBot Banner" width="1280"/>
</div>

---


## 🧰 はじめに

### 前提条件
- Python **3.10+**
- `git`（リポジトリのクローンに必要）
- 選択したLLMプロバイダー（OpenAI、Gemini、またはAnthropic）のAPIキー
- `Node.js` **18+**（オプション - ブラウザインターフェースにのみ必要）
- `conda`（オプション - 見つからない場合、インストーラーがMinicondaの自動インストールを提案します）

### どのセットアップを使えばいいですか？

> **迷ったらオプション1を選んでください。** すべて自動で処理されます。

| | オプション1 — サービスインストール | オプション2 — Condaインストール | オプション3 — 手動インストール |
|---|---|---|---|
| **対象ユーザー** | ほとんどのユーザー、初心者、テスト目的 | 独立環境が必要なCondaユーザー | 上級ユーザー、Pythonのカスタマイズ、完全制御 |
| **Python/環境を自動管理？** | ✅ 自動 | ✅ 自動 | ❌ 自分で管理 |
| **バックグラウンドで動作？** | ✅ はい、サービスとして | ❌ いいえ | ❌ いいえ |
| **起動方法** | `python craftbot.py install` | `python install.py --conda` | `python install.py` |

---

### ⭐ オプション1 — サービスインストール（推奨）

**これを選ぶなら：** CraftBotをすぐに使いたい場合 — バックグラウンドサービス、ログイン時の自動起動、デスクトップショートカット、手動操作不要。

`craftbot.py` がすべて処理します：Python環境、依存関係、バックグラウンドプロセス管理、自動起動の登録。

```bash
# 1. リポジトリをクローン
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. インストール、自動起動の登録、CraftBotの起動
python craftbot.py install
```

以上です。ターミナルは自動で閉じ、CraftBotはバックグラウンドで動作し、ブラウザが自動で開きます。**デスクトップショートカット**が作成されるので、ブラウザをいつでも再度開けます。

**インストール後のサービス管理：**

```bash
python craftbot.py start      # CraftBotをバックグラウンドで起動
python craftbot.py stop       # CraftBotを停止
python craftbot.py restart    # CraftBotを再起動
python craftbot.py status     # 実行中か確認、自動起動が有効かも確認
python craftbot.py logs       # 最近のログを確認
python craftbot.py uninstall  # 停止、自動起動削除、パッケージをアンインストール
```

> [!TIP]
> `install` または `start` の後、**CraftBotデスクトップショートカット**が自動作成されます。ブラウザを誤って閉じた場合は、ショートカットをダブルクリックして再度開けます。

---

### オプション2 — Condaインストール

**これを選ぶなら：** すでにcondaを使用していて、独立したconda環境でCraftBotを動かしたい場合。

`install.py --conda` は専用の `craftbot` conda環境を設定します。Minicondaが見つからない場合は自動的にインストールされます。

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

### Living UIを作成する3つの方法

1. **ゼロから構築する。** 望むものを自然な言葉で説明してください。CraftBotが
   データモデル、バックエンドAPI、React UIをスキャフォールドし、構造化された
   設計プロセスを通じてあなたと共に反復します。

<div align="center">
    <img src="assets/living-ui-custom-build.png" alt="Building a Living UI from scratch" width="448"/>
</div>

2. **マーケットプレイスからインストールする。** [living-ui-marketplace](https://github.com/CraftOS-dev/living-ui-marketplace)からコミュニティが作成したLiving UIを閲覧できます。

<div align="center">
    <img src="assets/living-ui-marketplace.png" alt="Living UI marketplace" width="448"/>
</div>

3. **既存のプロジェクトをインポートする。** Go、Node.js、Python、Rust、または静的なソースコード
   やGitHubリポジトリをCraftBotに指定してください。ランタイムを検出し、ヘルスチェックを構成し、
   Living UIとしてラップします。

<div align="center">
    <img src="assets/living-ui-import.png" alt="Importing an existing project as a Living UI" width="448"/>
</div>

### CraftBotをループの中に据えて進化し続ける

Living UIは決して「完成」することはありません。あなたのニーズが成長するにつれて、
機能の追加、ビューの再設計、新しいデータへの接続をエージェントに依頼できます。

CraftBotはすべてのLiving UIに埋め込まれ、**その状態を常に認識しています**。
現在のDOMとフォームの値を読み取り、REST APIを介してアプリデータを照会し、
あなたの代わりにアクションをトリガーできます。

---

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

### Node.jsがない（ブラウザモード用）
`python run.py`実行時に**「npm not found in PATH」**と表示される場合：
1. [nodejs.org](https://nodejs.org/)からダウンロード（LTSバージョンを選択）
2. インストールしてターミナルを再起動
3. `python run.py`を再度実行

**代替手段:** 代わりにCLIモードを使用（Node.js不要）：
```bash
python run.py --cli
```

### 依存関係でインストールが失敗する
インストーラーは解決策付きの詳細なエラーメッセージを提供します。インストールが失敗した場合：
- **Pythonバージョンを確認:** Python 3.10+であることを確認（`python --version`）
- **インターネット接続を確認:** インストール中に依存関係がダウンロードされます
- **pipキャッシュをクリア:** `pip install --upgrade pip`を実行して再試行

### Playwrightのインストール問題
Playwright chromiumのインストールはオプションです。失敗した場合：
- エージェントは他のタスクでは**問題なく動作します**
- スキップするか後でインストール: `playwright install chromium`
- WhatsApp Web連携にのみ必要

詳細なトラブルシューティングについては、[INSTALLATION_FIX.md](INSTALLATION_FIX.md)を参照してください。

---

## 🔌 外部サービス連携

エージェントはOAuthを使用してさまざまなサービスに接続できます。リリースビルドには埋め込みクレデンシャルが付属していますが、独自のクレデンシャルを使用することもできます。

### クイックスタート

埋め込みクレデンシャル付きのリリースビルドの場合:
```
/google login    # Google Workspaceに接続
/zoom login      # Zoomに接続
/slack invite    # Slackに接続
/notion invite   # Notionに接続
/linkedin login  # LinkedInに接続
```

### サービス詳細

| サービス | 認証タイプ | コマンド | シークレットが必要? |
|---------|-----------|---------|------------------|
| Google | PKCE | `/google login` | いいえ (PKCE) |
| Zoom | PKCE | `/zoom login` | いいえ (PKCE) |
| Slack | OAuth 2.0 | `/slack invite` | はい |
| Notion | OAuth 2.0 | `/notion invite` | はい |
| LinkedIn | OAuth 2.0 | `/linkedin login` | はい |

### 独自のクレデンシャルを使用する

独自のOAuthクレデンシャルを使用する場合は、`.env`ファイルに追加してください:

#### Google (PKCE - クライアントIDのみ必要)
```bash
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
```
1. [Google Cloud Console](https://console.cloud.google.com/)にアクセス
2. Gmail、カレンダー、ドライブ、People APIを有効化
3. **デスクトップアプリ**タイプとしてOAuthクレデンシャルを作成
4. クライアントIDをコピー（PKCEではシークレットは不要）

#### Zoom (PKCE - クライアントIDのみ必要)
```bash
ZOOM_CLIENT_ID=your-zoom-client-id
```
1. [Zoom Marketplace](https://marketplace.zoom.us/)にアクセス
2. OAuthアプリを作成
3. クライアントIDをコピー

#### Slack (両方必要)
```bash
SLACK_SHARED_CLIENT_ID=your-slack-client-id
SLACK_SHARED_CLIENT_SECRET=your-slack-client-secret
```
1. [Slack API](https://api.slack.com/apps)にアクセス
2. 新しいアプリを作成
3. OAuthスコープを追加: `chat:write`、`channels:read`、`users:read`など
4. クライアントIDとクライアントシークレットをコピー

#### Notion (両方必要)
```bash
NOTION_SHARED_CLIENT_ID=your-notion-client-id
NOTION_SHARED_CLIENT_SECRET=your-notion-client-secret
```
1. [Notion Developers](https://developers.notion.com/)にアクセス
2. 新しいインテグレーション（パブリックインテグレーション）を作成
3. OAuthクライアントIDとシークレットをコピー

#### LinkedIn (両方必要)
```bash
LINKEDIN_CLIENT_ID=your-linkedin-client-id
LINKEDIN_CLIENT_SECRET=your-linkedin-client-secret
```
1. [LinkedIn Developers](https://developer.linkedin.com/)にアクセス
2. アプリを作成
3. OAuth 2.0スコープを追加
4. クライアントIDとクライアントシークレットをコピー

---
## 🐳 コンテナで実行

リポジトリのルートには、Python 3.10、主要なシステムパッケージ（OCR用のTesseractを含む）、および`environment.yml`/`requirements.txt`で定義されたすべてのPython依存関係を含むDocker構成が含まれており、エージェントは隔離された環境で一貫して実行できます。

以下は、コンテナでエージェントを実行するためのセットアップ手順です。

### イメージのビルド

リポジトリのルートから:

```bash
docker build -t craftbot .
```

### コンテナの実行

イメージはデフォルトで`python -m app.main`でエージェントを起動するように構成されています。対話的に実行するには:

```bash
docker run --rm -it craftbot
```

環境変数を渡す必要がある場合は、envファイル（例えば`.env.example`に基づく）を渡します:

```bash
docker run --rm -it --env-file .env craftbot
```

コンテナの外部で永続化する必要があるディレクトリ（データやキャッシュフォルダなど）は`-v`を使用してマウントし、デプロイに必要に応じてポートや追加のフラグを調整してください。コンテナには、OCR（`tesseract`）や一般的なHTTPクライアント用のシステム依存関係が含まれているため、エージェントはコンテナ内でファイルやネットワークAPIを扱うことができます。

デフォルトでは、イメージはPython 3.10を使用し、`environment.yml`/`requirements.txt`からのPython依存関係をバンドルしているため、`python -m app.main`はそのまま動作します。

---

## 🤝 貢献方法

プルリクエストを歓迎します！ワークフロー（fork → `dev` ブランチから分岐 → PR）については [CONTRIBUTING.md](CONTRIBUTING.md) をご覧ください。すべてのプルリクエストは lint + スモークテスト CI で自動的に検証されます。質問や素早いやり取りをご希望の場合は、[Discord](https://discord.gg/ZN9YHc37HG) に参加するか、thamyikfoong(at)craftos.net までメールしてください。

## 🧾 ライセンス

このプロジェクトは[MITライセンス](LICENSE)の下でライセンスされています。このプロジェクトは自由に使用、ホスト、収益化できます（配布や収益化の場合は、このプロジェクトのクレジット表記が必要です）。

---

## ⭐ 謝辞

[CraftOS](https://craftos.net/)および貢献者[@zfoong](https://github.com/zfoong)と[@ahmad-ajmal](https://github.com/ahmad-ajmal)によって開発・維持されています。
**CraftBot**が役に立つと思われた場合は、リポジトリに⭐をつけて、他の人と共有してくださると嬉しいです！

---

## Star History

<a href="https://www.star-history.com/?repos=CraftOS-dev%2FCraftBot&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
 </picture>
</a>
