
<div align="center">
    <img src="assets/craftbot_readme_banner.png" alt="CraftBot Banner" width="1280"/>
</div>
<br>

<div align="center">
  <img src="https://img.shields.io/badge/OS-Windows-blue?logo=windows&logoColor=white" alt="Windows">
  <img src="https://img.shields.io/badge/OS-Linux-yellow?logo=linux&logoColor=black" alt="Linux">

  <a href="https://github.com/zfoong/CraftBot">
    <img src="https://img.shields.io/github/stars/zfoong/CraftBot?style=social" alt="GitHub Repo stars">
  </a>

  <img src="https://img.shields.io/github/license/zfoong/CraftBot" alt="License">

  <a href="https://discord.gg/ZN9YHc37HG">
    <img src="https://img.shields.io/badge/Discord-Join%20the%20community-5865F2?logo=discord&logoColor=white" alt="Discord">
  </a>
<br/>
<br/>

[![SPONSORED BY E2B FOR STARTUPS](https://img.shields.io/badge/SPONSORED%20BY-E2B%20FOR%20STARTUPS-ff8800?style=for-the-badge)](https://e2b.dev/startups)
</div>

<p align="center">
  <a href="README.md">English version here</a> | <a href="README.cn.md"> 中文版README </a>
</p>

## 🚀 概要
<h3 align="center">
CraftBotは、あなたのマシンに常駐し、24時間365日働くパーソナルAIアシスタントです。
</h3>

タスクを自律的に解釈し、アクションを計画し、目標を達成するために実行します。
あなたの好みや目的を学習し、人生の目標を達成するためのタスクを積極的に計画・開始します。
MCP、スキル、外部アプリとの連携をサポートしています。

CraftBotはあなたの命令を待っています。今すぐあなた専用のCraftBotをセットアップしましょう。

---

## ✨ 特徴

- **Bring Your Own Key (BYOK)** — OpenAI、Google Gemini、Anthropic Claude、BytePlus、ローカルOllamaモデルをサポートする柔軟なLLMプロバイダーシステム。プロバイダー間の切り替えが簡単です。
- **メモリシステム** — 一日を通して起きたイベントを深夜に整理・統合します。
- **プロアクティブエージェント** — あなたの好み、習慣、人生の目標を学習し、計画を立て、タスクを開始して（もちろん承認付きで）あなたの生活をより良くします。
- **外部ツール統合** — 埋め込みクレデンシャルとOAuthサポートにより、Google Workspace、Slack、Notion、Zoom、LinkedIn、Discord、Telegramに接続（今後さらに追加予定！）。
- **MCP** — 外部ツールやサービスでエージェント機能を拡張するためのModel Context Protocol統合。
- **スキル** — タスク計画、リサーチ、コードレビュー、Git操作などの組み込みスキルを含む拡張可能なスキルフレームワーク。
- **クロスプラットフォーム** — プラットフォーム固有のコードバリアントとDockerコンテナ化によるWindowsとLinuxの完全サポート。

> [!IMPORTANT]
> **GUIモードに関する注意:** GUIモードはまだ実験段階です。エージェントがGUIモードに切り替える際に問題が発生する可能性があります。この機能の改善に積極的に取り組んでいます。

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

### クイックインストール

```bash
# リポジトリをクローン
git clone https://github.com/zfoong/CraftBot.git
cd CraftBot

# 依存関係をインストール
python install.py

# エージェントを実行
python run.py
```

以上です！初回実行時にAPIキーの設定がガイドされます。

**注意:** Node.jsがインストールされていない場合、インストーラーがステップバイステップの手順をガイドします。ブラウザモードをスキップしてTUIを使用することもできます（以下のモードを参照）。

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
| **TUI** | `python run.py --tui` | なし | ターミナルUI、追加の依存関係なし |
| **CLI** | `python run.py --cli` | なし | コマンドライン、軽量 |
| **GUI** | `python run.py --gui` | `install.py --gui` | 視覚的フィードバック付きのデスクトップ自動化 |

**ブラウザモード**がデフォルトで推奨されます。Node.jsがない場合は、インストーラーがインストール手順を提供するか、代わりに**TUIモード**を使用できます。

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
| **TUIインターフェース** | 対話的なコマンドライン操作のためにTextualフレームワークで構築されたターミナルユーザーインターフェース。 |
| **GUIモジュール** | Dockerコンテナ、UI要素検出用のOmniParser、Gradioクライアントを使用した実験的なGUI自動化。 |

---

## 🔜 ロードマップ

- [X] **メモリモジュール** — 完了。
- [ ] **外部ツール統合** — さらに追加中！
- [X] **MCPレイヤー** — 完了。
- [X] **スキルレイヤー** — 完了。
- [X] **プロアクティブな動作** — 実装予定

---

## 🖥️ GUIモード（オプション）

GUIモードは画面自動化を有効にします - エージェントがデスクトップ環境を見て操作できるようになります。これはオプションで、追加のセットアップが必要です。

```bash
# GUIサポートをインストール（pip使用、conda不要）
python install.py --gui

# GUIサポートとcondaでインストール
python install.py --gui --conda

# GUIモードで実行
python run.py --gui
```

> [!NOTE]
> GUIモードは実験的機能であり、追加の依存関係が必要です（モデルウェイトで約4GB）。デスクトップ自動化が不要な場合は、これをスキップして代わりにBrowser/TUIモードを使用してください。追加の依存関係は必要ありません。

---

## 📋 コマンドリファレンス

### install.py

| フラグ | 説明 |
|------|-------------|
| `--gui` | GUIコンポーネント（OmniParser）をインストール |
| `--conda` | conda環境を使用（オプション） |
| `--cpu-only` | CPU専用のPyTorchをインストール（--guiと併用） |

### run.py

| フラグ | 説明 |
|------|-------------|
| (なし) | **ブラウザ**モードで実行（推奨、Node.jsが必要） |
| `--tui` | **ターミナルUI**モードで実行（追加の依存関係なし） |
| `--cli` | **CLI**モードで実行（軽量） |
| `--gui` | GUI自動化モードを有効化（先に `install.py --gui` が必要） |

**インストール例:**
```bash
# シンプルなpipインストール（condaなし）
python install.py

# GUIサポート付き（pip使用、condaなし）
python install.py --gui

# CPU専用システムでのGUI（pip使用、condaなし）
python install.py --gui --cpu-only

# conda環境を使用（condaユーザー向け推奨）
python install.py --conda

# GUIサポートとconda
python install.py --gui --conda

# condaを使用したCPU専用システムでのGUI
python install.py --gui --conda --cpu-only
```

**CraftBotの実行:**

```powershell
# ブラウザモード（デフォルト、Node.jsが必要）
python run.py

# TUIモード（Node.js不要）
python run.py --tui

# CLIモード（軽量）
python run.py --cli

# GPU/GUIモード
python run.py --gui

# conda環境で
conda run -n craftbot python run.py

# condaがPATHにない場合はフルパスを使用
&"$env:USERPROFILE\miniconda3\Scripts\conda.exe" run -n craftbot python run.py
```

**Linux/macOS (Bash):**
```bash
# ブラウザモード（デフォルト、Node.jsが必要）
python run.py

# TUIモード（Node.js不要）
python run.py --tui

# CLIモード（軽量）
python run.py --cli

# GPU/GUIモード
python run.py --gui

# conda環境で
conda run -n craftbot python run.py
```

> [!NOTE]
> **インストール:** インストーラーは依存関係が不足している場合、明確なガイダンスを提供します。Node.jsが見つからない場合は、インストールを促すか、TUIモードに切り替えることができます。インストールはGPUの可用性を自動検出し、必要に応じてCPU専用モードにフォールバックします。

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

**代替手段:** 代わりにTUIモードを使用（Node.js不要）：
```bash
python run.py --tui
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

### GPU/CUDAの問題
インストーラーはGPUの可用性を自動検出します：
- CUDAインストールが失敗した場合、自動的にCPUモードにフォールバックします
- 手動でCPUセットアップ: `python install.py --gui --cpu-only`

詳細なトラブルシューティングについては、[INSTALLATION_FIX.md](INSTALLATION_FIX.md)を参照してください。

---

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
## コンテナで実行

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

コンテナの外部で永続化する必要があるディレクトリ（データやキャッシュフォルダなど）は`-v`を使用してマウントし、デプロイに必要に応じてポートや追加のフラグを調整してください。コンテナには、OCR（`tesseract`）、画面自動化（`pyautogui`、`mss`、X11ユーティリティ、仮想フレームバッファ）、および一般的なHTTPクライアント用のシステム依存関係が含まれているため、エージェントはコンテナ内でファイル、ネットワークAPI、GUI自動化を扱うことができます。

### GUI/画面自動化の有効化

GUIアクション（マウス/キーボードイベント、スクリーンショット）にはX11サーバーが必要です。ホストディスプレイにアタッチするか、`xvfb`でヘッドレスで実行できます:

* ホストディスプレイを使用（X11を使用するLinuxが必要）:

  ```bash
  docker run --rm -it
    -e DISPLAY=$DISPLAY \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v $(pwd)/data:/app/app/data \
    craftbot
  ```

  エージェントが読み書きする必要があるフォルダには、追加の`-v`マウントを追加してください。

* 仮想ディスプレイでヘッドレス実行:

  ```bash
	docker run --rm -it --env-file .env craftbot bash -lc "Xvfb :99 -screen 0 1920x1080x24 & export DISPLAY=:99 && exec python -m app.main"
  ```

デフォルトでは、イメージはPython 3.10を使用し、`environment.yml`/`requirements.txt`からのPython依存関係をバンドルしているため、`python -m app.main`はそのまま動作します。

---

## 🤝 貢献方法

貢献と提案を歓迎します！[@zfoong](https://github.com/zfoong) @ thamyikfoong(at)craftos.net までご連絡ください。現在、チェック機能を設定していないため、直接的な貢献は受け付けられませんが、提案やフィードバックは大変ありがたく思います。

## 🧾 ライセンス

このプロジェクトは[MITライセンス](LICENSE)の下でライセンスされています。このプロジェクトは自由に使用、ホスト、収益化できます（配布や収益化の場合は、このプロジェクトのクレジット表記が必要です）。

---

## ⭐ 謝辞

[CraftOS](https://craftos.net/)および貢献者[@zfoong](https://github.com/zfoong)と[@ahmad-ajmal](https://github.com/ahmad-ajmal)によって開発・維持されています。
**CraftBot**が役に立つと思われた場合は、リポジトリに⭐をつけて、他の人と共有してくださると嬉しいです！
