<div align="center">
    <img src="assets/README_cover.png" alt="CraftBot" width="1280"/>
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

  <a href="https://deepwiki.com/CraftOS-dev/CraftBot">
    <img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki">
  </a>
</p>

<div align="center">
	
[![SPONSORED BY E2B FOR STARTUPS](https://img.shields.io/badge/SPONSORED%20BY-E2B%20FOR%20STARTUPS-ff8800?style=for-the-badge)](https://e2b.dev/startups)
</div>

<p align="center">
  <a href="README.md">English</a> | <a href="README.cn.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ko.md">한국어</a> | <a href="README.es.md">Español</a> | <a href="README.pt-BR.md">Português</a> | <a href="README.fr.md">Français</a> | <a href="README.de.md">Deutsch</a>
</p>

## ✨ 主な特徴

自前のSaaSツールを作って動かせるAIエージェントというだけでなく、CraftBotはエージェントハーネスのコア機能をひと通り備えており、あなたのタスク・ツール・記憶・日々のワークフローと一緒に動く汎用AIエージェントとして機能します。

- **エージェントプロファイル** 40以上のエージェントプロファイル(CEOエージェント、財務エージェント、マーケティングリードエージェント、DevOpsエンジニア、動画プロデューサーエージェントなど37種類)があなたのために働く準備が整っています。**[CraftBot Agent Bundles](https://github.com/CraftOS-dev/craftbot-agent-bundles)** から欲しいロールを見つけ、ワンクリックでインポートできます。
- **プレイブックカタログ** AIエージェントで何を自動化すればよいかわからない?CraftBotには120のプレイブック(19カテゴリーにまたがる)がすぐに使える状態で用意されています。上部バーからプレイブックピッカーを開き、プレイブックを選ぶと、すぐにタスクを実行してくれます。
- **Agent App.** CraftBotの中で動くカスタムアプリを構築・インポート・進化させられます。エージェントはUIの状態を常に把握し、そのデータを直接読み書き・操作できます。
- **マルチタスクとセッションルーティング.** まだ`/new`コマンドを叩いていますか？CraftBotは、いつ新しいセッションを始め、いつ既存のタスクを再開すべきかを自分で判断し、会話とコンテキストを一本化します。
- **セルフホスト & BYOK.** OpenAI、Google Gemini、Anthropic Claude、OpenRouterなどに対応する柔軟なLLMプロバイダーシステム。Ollamaを使えば、自分のモデルをトークン消費ゼロでホストすることも可能です。
- **メモリーシステム.** CraftBotとのやり取りから構築されるセカンドブレイン。ハイブリッド構成:RAG + ナレッジグラフ + エージェントファイルシステム。CraftBotは深夜に「夢を見て」、その日の出来事を統合します。
- **能動的なエージェント.** あなたの好み、習慣、人生の目標を学習。そのうえで計画を立て、タスクを起動(もちろん承認付きで)し、あなたの人生をより良くする手助けをします。
- **外部ツールとの連携.** Google Workspace、Slack、Notion、Zoom、LinkedIn、Discord、Telegramなどのアプリと接続可能(今後さらに追加予定)。OAuthまたは自分のキーでの利用に対応しています。各連携には複数のアカウントを接続できます。
- **スキル & MCP.** 150以上のMCPと170以上のスキルが利用可能。新しいスキルやMCPもすぐに導入できます。完了したタスクからワンクリックでスキルを作成・改善することもできます。
- **ブラウザでもターミナルでも.** あなたの使い方に合わせて選べます。日常使いには手軽なブラウザUIを、またはチャット・設定・Agent Appをそのまま使える本格的なターミナル版（`python run.py --tui`）をどうぞ。

---


## 🧰 はじめに

**必要条件**

- Windows 10 または 11(x64)、macOS 12 以降(Apple Silicon または Intel)、または Linux(x86_64 または ARM64)
- 5 GB 以上の空きディスク容量
- LLM プロバイダー(OpenAI、Anthropic、Google Gemini、OpenRouter など)の API キー、または Ollama で動かすローカルモデル
- ソースからインストールする場合のみ: Python 3.8 以降。Node.js は不要です。

### 方法 1: インストーラー(推奨、Python や Git は不要)

[最新リリース](https://github.com/CraftOS-dev/CraftBot/releases/latest)から、お使いのシステム用のファイルをダウンロードしてください。

| システム | ファイル |
|---|---|
| Windows(x64) | `CraftBotInstaller-windows.exe` |
| macOS(Apple Silicon と Intel) | `CraftBotInstaller-macos.zip` |
| Linux(x86_64) | `CraftBotInstaller-linux-x86_64` |
| Linux(ARM64) | `CraftBotInstaller-linux-aarch64` |

ファイルを開いて **Install CraftBot** をクリックします。インストーラーが CraftBot に必要なものをすべてダウンロードし、CraftBot を起動してブラウザで開きます。

インストーラーはまだコード署名されていないため、初回の起動時に次の操作が 1 つ必要です。

- **Windows:** SmartScreen に「Windows によって PC が保護されました」と表示されたら、**詳細情報**(More info)をクリックし、**実行**(Run anyway)をクリックします。
- **macOS:** ファイルを解凍して `CraftBotInstaller.app` を開きます。macOS 15 以降では最初の起動がブロックされます。**システム設定 > プライバシーとセキュリティ** を開き、CraftBotInstaller に関するメッセージの横にある **このまま開く**(Open Anyway)をクリックして確認します。macOS 12 から 14 では、アプリを右クリックして **開く**(Open)を選びます。
- **Linux:** ファイルに実行権限を付け、デスクトップセッションから実行します(デスクトップのないサーバーではソースからインストールしてください)。
  ```bash
  chmod +x CraftBotInstaller-linux-x86_64
  ./CraftBotInstaller-linux-x86_64
  ```

### 方法 2: ソースからインストール

コンピューターにすでにある Python 3.8 以降であれば、どのバージョンでも使えます。CraftBot は専用の Python 3.10 と Node.js 24 を自分でダウンロードし、システムにインストールされている Python や Node.js は変更しません。

```bash
git clone --depth 1 https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot
```

続いて、お使いのシステムに合わせてインストールコマンドを実行します。

```bash
# Windows
python craftbot.py install        # または: py craftbot.py install

# macOS と Linux
python3 craftbot.py install
```

- **Git がない場合:** [リポジトリのページ](https://github.com/CraftOS-dev/CraftBot)で **Code > Download ZIP** をクリックし、解凍したフォルダーでターミナルを開いて同じコマンドを実行します。
- **Python がない、または 3.8 より古い場合:** インストーラー(方法 1)を使ってください。

初回のインストールでは約 1 GB をダウンロードするため、一般的な回線で数分かかります。完了すると CraftBot はバックグラウンドで動作し、ブラウザで http://localhost:7925 を開き、デスクトップショートカットを作成します。ポート 7925 または 7926 が使用中の場合は、次に空いているポートを使い、開くべきアドレスを表示します。

初回起動時には、ブラウザのオンボーディングで LLM の API キーを入力します。キーは `app/config/settings.json` に保存され(後から設定画面で変更できます)、CraftBot が `.env` ファイルから API キーを読み込むことはありません。

### CraftBot の管理

インストール時と同じ `python` または `python3` コマンドを使います。

```bash
python craftbot.py start      # CraftBot をバックグラウンドで起動
python craftbot.py stop       # CraftBot を停止
python craftbot.py restart    # CraftBot を再起動
python craftbot.py status     # 稼働状況と自動起動の有無を確認
python craftbot.py logs       # 直近 50 行のログを表示(さらに見るには logs -n 200)
python craftbot.py uninstall  # 停止し、自動起動を解除し、パッケージをアンインストール
python run.py --tui           # ブラウザではなくターミナルで実行
```

インストーラーを使っている場合は、インストーラーのウィンドウから同じ操作ができます(**Start**、**Stop**、**Repair**、**Uninstall**)。

> [!TIP]
> `install`や`start`の後には、**CraftBotのデスクトップショートカット**が自動で作成されます。ブラウザを閉じてしまった場合は、このショートカットをダブルクリックすると再び開けます。

---

## 🌱 Agent App

**Agent Appは、あなたのニーズに合わせて進化していくシステム/アプリ/ダッシュボードです。**

<div align="center">
    <img src="assets/agent_app_banner.gif" alt="CraftBot Banner" width="1280"/>
</div>

- AIコパイロット付きのカンバンボードが欲しい?
- 自分のワークフローにぴったり合うカスタムCRMは?
- CraftBotがあなたに代わって読み取り・操作できる社内ダッシュボードは?

Agent Appとして立ち上げれば、CraftBotと並んで動作し、あなたのニーズの変化に合わせて成長します。

### Agent Appを作る3つの方法

1. **ゼロから構築.** 欲しいものを自然な言葉で説明してください。CraftBotが
   データモデル、バックエンドAPI、ReactのUIを足場として組み上げ、
   構造化された設計プロセスを通して一緒に改善していきます。

<div align="center">
    <img src="assets/agent-app-custom-build.png" alt="Building a Agent App from scratch" width="448"/>
</div>

2. **マーケットプレイスからインストール.** コミュニティが作ったAgent Appを[living-ui-marketplace](https://github.com/CraftOS-dev/living-ui-marketplace)から探せます。

<div align="center">
    <img src="assets/living-ui-marketplace.png" alt="Agent App marketplace" width="448"/>
</div>

3. **既存プロジェクトをインポート.** Go、Node.js、Python、Rust、
   または静的なソースコードやGitHubリポジトリをCraftBotに渡してください。ランタイムを検出し、ヘルスチェックを設定し、Agent Appとしてラップします。

<div align="center">
    <img src="assets/agent-app-import.png" alt="Importing an existing project as a Agent App" width="448"/>
</div>

### CraftBotを内部に組み込んだまま進化し続ける

Agent Appに「完成」はありません。ニーズが変われば、機能を追加したり、
ビューをリデザインしたり、新しいデータと連携させたり、エージェントに頼んでください。

CraftBotはすべてのAgent Appに組み込まれており、**状態を常に把握**しています。
現在のDOMやフォーム値を読み取り、REST API経由で
アプリのデータを参照し、あなたに代わってアクションを起こせます。

### SaaSツールをオープンに、生き続けるものへ

自分専用のAgent Appを構築・カスタマイズ・進化させ、自分の用途に完璧には合わないサブスクリプションツールへの依存を減らしていきましょう。

---
 
# 5分で試せる3つのAgent App
 
- **📋 カンバンボード**: タスク、フォローアップ、CTAをすべて一か所に。CraftBotが操作してPM業務を肩代わりできます。
- **📊 習慣トラッカー**: 習慣を作り、追跡する。開発者がコミットを刻むように、GitHub風のアクティビティカレンダーで習慣を可視化。
- **🐦 Luolinglo**: Duolingoではないですが、新しい言語を学び、フラッシュカードを作り、CraftBotと一緒に練習できます。

**[Agent Appマーケットプレイスを見る・投稿する →](https://craftos.net/marketplace)**

---

## 🔧 トラブルシューティングとよくある問題

**まずログを確認してください。** `python craftbot.py logs` で直近 50 行を表示できます(さらに見るには `logs -n 200`)。`install` や `start` が失敗した場合は、ログの末尾を表示してエラーで終了します。`python craftbot.py doctor` は何も変更せずに各インストール手順を確認します。インストーラーでは **Open log** をクリックします。

**インストールは何度実行しても安全です。** `python craftbot.py install` は成功済みの手順を飛ばし、残りだけを再試行します。インストーラーでは **Repair** をクリックします。

### ポート 7925 または 7926 が使用中

CraftBot は次に空いているポートに切り替え、開くべきアドレスを表示します。ポートを自分で指定するには次のようにします。

```bash
python craftbot.py start --frontend-port 8925 --backend-port 8926
```

### プロキシや社内ネットワーク

すべてのダウンロード(Python、pip、npm、Node.js)は標準のプロキシ環境変数を使います。インストールの前に、同じターミナルで設定してください。

```bash
# macOS と Linux
export HTTPS_PROXY=http://proxy.example.com:8080
export HTTP_PROXY=http://proxy.example.com:8080
export NO_PROXY=localhost,127.0.0.1
python3 craftbot.py install
```

```powershell
# Windows PowerShell
$env:HTTPS_PROXY = "http://proxy.example.com:8080"
$env:HTTP_PROXY = "http://proxy.example.com:8080"
$env:NO_PROXY = "localhost,127.0.0.1"
python craftbot.py install
```

TLS 通信を検査するネットワークでも追加の設定は不要です。CraftBot は OS の証明書ストアにある証明書を信頼します。

### ダウンロードが遅い、またはつながらない(中国本土など)

インストールの前に、ダウンロード先をミラーに向けてください。

| 変数 | 用途 | 例 |
|---|---|---|
| `PIP_INDEX_URL` | Python パッケージ | `https://pypi.tuna.tsinghua.edu.cn/simple` |
| `npm_config_registry` | npm パッケージ | `https://registry.npmmirror.com` |
| `HF_ENDPOINT` | 埋め込みモデル | `https://hf-mirror.com` |
| `CRAFTBOT_MIRRORS` | Python、Node.js、PocketBase、埋め込みモデルのダウンロード | 下記参照 |

`CRAFTBOT_MIRRORS` は、`prefix=replacement`(プレフィックス=置き換え先)形式の URL 書き換えルールをセミコロンで区切って並べたものです。

```bash
export CRAFTBOT_MIRRORS="https://github.com/=https://<your-github-proxy>/https://github.com/;https://nodejs.org/dist/=https://npmmirror.com/mirrors/node/"
```

Python パッケージとメモリ用の埋め込みモデルは、ミラーを使っても固定された SHA-256 チェックサムで検証されるため、ミラーがそれらを変えることはできません。Python と Node.js のランタイムはチェックサムが固定されていないため、信頼できるミラーだけを使ってください。Windows PowerShell では `export` の代わりに `$env:NAME = "value"` で変数を設定します。

### デスクトップのないサーバー

サーバーでソースからインストールし、ブラウザは開かないようにします。

```bash
python3 craftbot.py install --no-open-browser
```

CraftBot は `localhost` で待ち受け、`localhost` 宛てのブラウザ接続だけを受け付けます。自分のコンピューターから使うには、両方のポートを同じ番号で転送する SSH トンネルを作成し、自分のコンピューターで http://localhost:7925 を開きます。

```bash
ssh -L 7925:localhost:7925 -L 7926:localhost:7926 user@server
```

`CRAFTBOT_BIND_HOST` を設定すると、CraftBot は別のネットワークインターフェースで待ち受けます(Docker イメージでは `0.0.0.0`)。リモートからのアクセスには、引き続き SSH トンネルを使ってください。

### Linux: 再起動後に CraftBot が起動しない

自動起動は systemd のユーザーサービスなので、systemd のユーザーセッションが必要です。ログインしなくても起動時に CraftBot を開始し、ログアウト後も動かし続けるには、次のコマンドを一度実行します。

```bash
loginctl enable-linger $USER
```

systemd がない環境(systemd を有効にしていない WSL など)では、起動のたびに `python3 craftbot.py start` を実行してください。

### macOS: インストーラーがブロックされる

インストーラーはまだコード署名されていません。macOS 15 以降では、一度開こうとした後に **システム設定 > プライバシーとセキュリティ** を開き、**このまま開く**(Open Anyway)をクリックします。macOS 12 から 14 では、アプリを右クリックして **開く**(Open)を選びます。

### Windows: SmartScreen がインストーラーをブロックする

**詳細情報**(More info)をクリックし、**実行**(Run anyway)をクリックします。この警告は、インストーラーがまだコード署名されていないために表示されます。

### Windows: `python` を実行すると Microsoft Store が開く

Python がインストールされていません。インストーラーを使うか、[python.org](https://www.python.org/downloads/) から Python をインストールして `py craftbot.py install` を実行してください。

### CraftBot のデータを別の場所に置く

インストールの前に `CRAFTBOT_HOME` にフォルダーを指定すると、CraftBot のデータとダウンロードしたランタイムがすべてそこに保存されます(容量の大きいドライブなど)。自動起動でもこの設定が引き継がれます。

### ブラウザ機能(Playwright)

Mini Browser とブラウザ自動化は Playwright の Chromium を使います。このダウンロードに失敗しても、CraftBot のほかの機能はそのまま使えます。後で `python craftbot.py install` をもう一度実行すると再試行します。

---

## 🐳 コンテナで実行する

Docker イメージは、必要なものがすべてプリインストールされた状態で CraftBot をブラウザモードで実行します。内容は Python 3.10 とロックされた依存関係、Node.js 24、ブラウザ UI、PocketBase、Playwright の Chromium です。

リポジトリのルートで次を実行します。

```bash
docker compose up -d
```

初回のビルドには数分かかります。その後 http://localhost:7925 を開き、オンボーディングで LLM の API キーを入力します。

設定と API キー、エージェントのファイル、メモリー、ログは `craftbot-data` ボリュームに保存されるため、コンテナの再起動やイメージの再ビルド後も残ります。

```bash
docker compose logs -f craftbot              # ログを追跡表示
docker compose ps                            # ヘルスチェックを含む状態を確認
docker compose down                          # 停止(データボリュームは残ります)
git pull && docker compose up -d --build     # 最新バージョンに更新
```

- CraftBot の UI には独自のログイン機能がないため、ポートは `127.0.0.1` にのみ公開されます。リモートサーバーでもこの設定のままにし、トラブルシューティングで説明している SSH トンネルで接続してください。ホスト側のポートは 7925 と 7926 のままにしてください。CraftBot は、これらのポートへの `localhost` 宛てのブラウザ接続だけを受け付けます。
- シェル、または `docker-compose.yml` と同じフォルダーの `.env` ファイルで設定したプロキシとミラーの変数(`HTTPS_PROXY`、`PIP_INDEX_URL`、`HF_ENDPOINT`、`CRAFTBOT_MIRRORS` と、`.env.example` に記載のその他の変数)は、コンテナに渡されます。
- Agent App はコンテナ内のポート 3100 から 3199 で動作し、現時点ではホストのブラウザから開けません。Agent App を使う場合は、インストーラーまたはソースからのインストールを使ってください。
- Compose を使わない場合:
  ```bash
  docker build -t craftbot .
  docker run -d --name craftbot -p 127.0.0.1:7925:7925 -p 127.0.0.1:7926:7926 --shm-size 1g -v craftbot-data:/data craftbot
  ```

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

<a href="https://star-history.dera.page/#CraftOS-dev/CraftBot&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
 </picture>
</a>
