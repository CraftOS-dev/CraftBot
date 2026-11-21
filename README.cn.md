<div align="center">
    <img src="assets/README_cover.png" alt="CraftBot" width="1280"/>
</div>

大多数 Agent 框架止步于对话和工具调用,CraftBot 走得更远。它会自己构建、演进并运行 SaaS 工具,然后通过这套工具层与你沟通,并替你完成自动化工作。

除此之外,CraftBot 拥有通用 Agent 框架的全部核心能力。它像一位远程员工一样执行任务、记住你的偏好与目标,并主动帮助你规划和推进对你重要的事情。

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
  <a href="README.md">English</a> | <a href="README.ja.md">日本語</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ko.md">한국어</a> | <a href="README.es.md">Español</a> | <a href="README.pt-BR.md">Português</a> | <a href="README.fr.md">Français</a> | <a href="README.de.md">Deutsch</a>
</p>

## ✨ 核心特性

除了能够创建并运行自有 SaaS 工具,CraftBot 还具备 Agent 框架的全部核心能力,可以作为一个通用 AI Agent 陪你处理任务、工具、记忆与日常工作流。

- **Agent 配置档案** 40+ Agent 配置档案(CEO Agent、财务 Agent、市场负责人 Agent、DevOps 工程师、视频制作 Agent 等共 37 种)随时为你服务。从 **[CraftBot Agent Bundles](https://github.com/CraftOS-dev/craftbot-agent-bundles)** 找到所需角色,一键导入。
- **Playbook 目录** 不知道如何用 AI Agent 自动化?CraftBot 内置 120 个 Playbook(覆盖 19 个分类)随时可用。从顶部栏打开 Playbook 选择器,挑选一个 Playbook,它就会开始为你执行任务。
- **Agent App.** 在 CraftBot 内部构建、导入或演进自定义应用。Agent 始终感知 UI 状态,并能直接读取、写入和操作其中的数据。
- **多任务与会话路由.** 还在手动敲 `/new` 吗?CraftBot 能自行判断何时开启新会话、何时继续旧任务,让对话与上下文保持统一。
- **自托管与 BYOK.** 灵活的 LLM 提供商体系,支持 OpenAI、Google Gemini、Anthropic Claude、OpenRouter 等。也可以用 Ollama 自行托管模型,实现零 Token 消耗。
- **记忆系统.** 从你与 CraftBot 的交互中构建的第二大脑。混合方案:RAG + 知识图谱 + Agent 文件系统。CraftBot 会在午夜「做梦」,整合一整天发生的事件。
- **主动型 Agent.** 学习你的偏好、习惯和人生目标,然后主动进行规划并发起任务(当然要经过你的同意),帮你在生活中变得更好。
- **外部工具集成.** 连接你的应用,例如 Google Workspace、Slack、Notion、Zoom、LinkedIn、Discord、Telegram 等(还有更多正在路上),支持 OAuth 或使用你自己的密钥。每个集成都可以连接多个账号。
- **Skills 与 MCP.** 已就绪 150+ MCP 与 170+ Skills,支持快速安装新的 Skills 与 MCP,也可以从已完成的任务中一键创建或改进 Skills。
- **浏览器或终端.** 用最适合你的方式使用 CraftBot:日常使用走简洁的浏览器 UI,也可以使用完整的终端版(`python run.py --tui`),聊天、设置和 Agent App 都一样。

---


## 🧰 快速开始

**环境要求**

- Windows 10 或 11(x64)、macOS 12 或更高版本(Apple Silicon 或 Intel),或 Linux(x86_64 或 ARM64)
- 至少 5 GB 可用磁盘空间
- 一个 LLM 服务商的 API 密钥(例如 OpenAI、Anthropic、Google Gemini 或 OpenRouter),或通过 Ollama 运行的本地模型
- 仅源码安装需要:Python 3.8 或更高版本。无需安装 Node.js。

### 方式一:安装程序(推荐,无需 Python 或 Git)

从[最新发布页](https://github.com/CraftOS-dev/CraftBot/releases/latest)下载适合你系统的文件:

| 系统 | 文件 |
|---|---|
| Windows(x64) | `CraftBotInstaller-windows.exe` |
| macOS(Apple Silicon 和 Intel) | `CraftBotInstaller-macos.zip` |
| Linux(x86_64) | `CraftBotInstaller-linux-x86_64` |
| Linux(ARM64) | `CraftBotInstaller-linux-aarch64` |

打开后点击 **Install CraftBot**。安装程序会下载 CraftBot 所需的全部内容,启动 CraftBot,并在浏览器中打开它。

安装程序目前尚未进行代码签名,因此首次启动需要多一步操作:

- **Windows:** 如果 SmartScreen 提示“Windows 已保护你的电脑”,点击 **更多信息**(More info),再点击 **仍要运行**(Run anyway)。
- **macOS:** 解压后打开 `CraftBotInstaller.app`。在 macOS 15 及更高版本上,首次打开会被拦截:打开 **系统设置 > 隐私与安全性**,在关于 CraftBotInstaller 的提示旁点击 **仍要打开**(Open Anyway)并确认。在 macOS 12 至 14 上,右键点击该应用并选择 **打开**(Open)。
- **Linux:** 为文件添加可执行权限,然后在桌面会话中运行(没有桌面环境的服务器请使用源码安装):
  ```bash
  chmod +x CraftBotInstaller-linux-x86_64
  ./CraftBotInstaller-linux-x86_64
  ```

### 方式二:从源码安装

电脑上已有的任意 Python 3.8 或更高版本即可。CraftBot 会下载自己专用的 Python 3.10 和 Node.js 24,不会改动系统中已安装的 Python 或 Node.js。

```bash
git clone --depth 1 https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot
```

然后运行对应系统的安装命令:

```bash
# Windows
python craftbot.py install        # 或:py craftbot.py install

# macOS 和 Linux
python3 craftbot.py install
```

- **没有 Git?** 在[仓库页面](https://github.com/CraftOS-dev/CraftBot)点击 **Code > Download ZIP**,解压后在解压出的文件夹中打开终端,运行同样的命令。
- **没有 Python,或版本低于 3.8?** 请使用安装程序(方式一)。

首次安装大约需要下载 1 GB,在一般网络下需要几分钟。完成后,CraftBot 会在后台运行,在浏览器中打开 http://localhost:7925,并创建桌面快捷方式。如果 7925 或 7926 端口已被占用,CraftBot 会改用下一个空闲端口,并打印需要打开的地址。

首次启动时,浏览器中的引导流程会请你填写 LLM API 密钥。CraftBot 将其保存在 `app/config/settings.json` 中(之后可在设置中修改),不会从 `.env` 文件读取 API 密钥。

### 管理 CraftBot

使用与安装时相同的 `python` 或 `python3` 命令:

```bash
python craftbot.py start      # 在后台启动 CraftBot
python craftbot.py stop       # 停止 CraftBot
python craftbot.py restart    # 重启 CraftBot
python craftbot.py status     # 查看运行状态以及是否已启用自启动
python craftbot.py logs       # 查看最近 50 行日志(更多:logs -n 200)
python craftbot.py uninstall  # 停止运行、移除自启动并卸载依赖包
python run.py --tui           # 在终端中运行,而不是在浏览器中
```

使用安装程序的用户可以在安装程序窗口中完成同样的操作(**Start**、**Stop**、**Repair**、**Uninstall**)。

> [!TIP]
> 执行 `install` 或 `start` 之后会自动创建 **CraftBot 桌面快捷方式**。如果关闭了浏览器,双击该快捷方式即可重新打开。

---

## 🌱 Agent App

**Agent App 是会随你的需求一同演进的系统/应用/仪表盘。**

<div align="center">
    <img src="assets/agent_app_banner.gif" alt="CraftBot Banner" width="1280"/>
</div>

- 想要一个内置 AI 协作伙伴的看板?
- 一套完全贴合你工作流的定制 CRM?
- 一个 CraftBot 能替你读取并操作的公司仪表盘?

将它作为 Agent App 启动:它与 CraftBot 并行运行,并随着你的需求变化而成长。

### 创建 Agent App 的三种方式

1. **从零构建.** 用自然语言描述你想要的东西,CraftBot
   会搭好数据模型、后端 API 和 React 前端,
   并通过一套结构化的设计流程与你不断迭代。

<div align="center">
    <img src="assets/agent-app-custom-build.png" alt="Building a Agent App from scratch" width="448"/>
</div>

2. **从市场安装.** 在 [living-ui-marketplace](https://github.com/CraftOS-dev/living-ui-marketplace) 中浏览社区构建的 Agent App。

<div align="center">
    <img src="assets/living-ui-marketplace.png" alt="Agent App marketplace" width="448"/>
</div>

3. **导入现有项目.** 把 Go、Node.js、Python、Rust
   或者静态源码、GitHub 仓库交给 CraftBot,它会自动识别运行时、配置健康检查,并把它封装成一个 Agent App。

<div align="center">
    <img src="assets/agent-app-import.png" alt="Importing an existing project as a Agent App" width="448"/>
</div>

### 让 CraftBot 持续参与的不断演进

Agent App 永远没有「完成」这一说。需求一变,就让 Agent 给它加功能、
改版页面或接入新数据源。

CraftBot 嵌入在每个 Agent App 之中,并且**对其状态保持感知**:
它可以读取当前 DOM 和表单值、通过 REST API 查询应用数据,
并代替你触发操作。

### 让 SaaS 工具保持开放与鲜活

构建、定制并不断演进属于自己的 Agent App,减少对那些从未真正为你量身定制的订阅工具的依赖。

---
 
# 三个 5 分钟内可以试玩的 Agent App
 
- **📋 看板**:把所有任务、跟进事项和待办集中到一个地方,CraftBot 可以接手运营,替你完成 PM 工作。
- **📊 习惯追踪器**:培养并追踪自己的习惯,用类 GitHub 风格的活动日历像开发者一样维护你的习惯。
- **🐦 Luolinglo**:不是多邻国,但你可以学习新语言、制作单词卡片,并和 CraftBot 一起练习。

**[浏览 Agent App 市场并参与贡献 →](https://craftos.net/marketplace)**

---

## 🔧 故障排查与常见问题

**先查看日志。** `python craftbot.py logs` 显示最近 50 行日志(更多:`logs -n 200`)。`install` 或 `start` 失败时,会打印日志末尾并以错误状态退出。`python craftbot.py doctor` 会逐项检查安装步骤,不做任何改动。在安装程序中可点击 **Open log**。

**重新运行安装是安全的。** `python craftbot.py install` 会跳过已成功的步骤,只重试其余步骤。在安装程序中可点击 **Repair**。

### 7925 或 7926 端口被占用

CraftBot 会改用下一个空闲端口,并打印需要打开的地址。如需自行指定端口:

```bash
python craftbot.py start --frontend-port 8925 --backend-port 8926
```

### 代理或公司网络

所有下载(Python、pip、npm、Node.js)都会使用标准代理环境变量。请在安装前于同一个终端中设置:

```bash
# macOS 和 Linux
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

对 TLS 流量进行检查的网络无需额外设置:CraftBot 信任操作系统证书库中的证书。

### 下载缓慢或无法访问(例如在中国大陆)

安装前将下载指向镜像:

| 变量 | 用途 | 示例 |
|---|---|---|
| `PIP_INDEX_URL` | Python 包 | `https://pypi.tuna.tsinghua.edu.cn/simple` |
| `npm_config_registry` | npm 包 | `https://registry.npmmirror.com` |
| `HF_ENDPOINT` | 嵌入模型 | `https://hf-mirror.com` |
| `CRAFTBOT_MIRRORS` | Python、Node.js、PocketBase 和嵌入模型的下载 | 见下文 |

`CRAFTBOT_MIRRORS` 是以分号分隔的 `prefix=replacement`(前缀=替换地址)URL 改写规则:

```bash
export CRAFTBOT_MIRRORS="https://github.com/=https://<your-github-proxy>/https://github.com/;https://nodejs.org/dist/=https://npmmirror.com/mirrors/node/"
```

Python 依赖包、Python 和 Node.js 运行时以及记忆嵌入模型都会按固定的 SHA-256 校验值进行校验,因此镜像无法改变它们。在 Windows PowerShell 中,请用 `$env:NAME = "value"` 代替 `export` 设置变量。

### 没有桌面环境的服务器

在服务器上从源码安装,并且不打开浏览器:

```bash
python3 craftbot.py install --no-open-browser
```

CraftBot 只监听 `localhost`,并且只接受以 `localhost` 访问的浏览器连接。要从自己的电脑访问,请建立一个以相同端口号转发两个端口的 SSH 隧道,然后在自己的电脑上打开 http://localhost:7925:

```bash
ssh -L 7925:localhost:7925 -L 7926:localhost:7926 user@server
```

`CRAFTBOT_BIND_HOST` 可以让 CraftBot 监听其他网络接口(Docker 镜像使用 `0.0.0.0`)。远程访问仍应通过 SSH 隧道进行。

### Linux:重启后 CraftBot 没有自动启动

自启动是一个 systemd 用户服务,因此需要 systemd 用户会话。如需在开机时无需登录即可启动 CraftBot,并在注销后继续运行,请执行一次:

```bash
loginctl enable-linger $USER
```

在没有 systemd 的环境中(例如未启用 systemd 的 WSL),请在每次开机后运行 `python3 craftbot.py start`。

### macOS:安装程序被拦截

安装程序尚未进行代码签名。在 macOS 15 及更高版本上,先尝试打开一次,然后打开 **系统设置 > 隐私与安全性** 并点击 **仍要打开**(Open Anyway)。在 macOS 12 至 14 上,右键点击该应用并选择 **打开**(Open)。

### Windows:SmartScreen 拦截安装程序

点击 **更多信息**(More info),再点击 **仍要运行**(Run anyway)。出现该提示是因为安装程序尚未进行代码签名。

### Windows:输入 `python` 后打开了 Microsoft Store

说明系统中没有安装 Python。请使用安装程序,或从 [python.org](https://www.python.org/downloads/) 安装 Python 后运行 `py craftbot.py install`。

### 将 CraftBot 的数据存放在其他位置

安装前将 `CRAFTBOT_HOME` 设置为某个文件夹(例如容量更大的磁盘上的文件夹),CraftBot 的全部数据和下载的运行时都会存放在那里。自启动会保留该设置。

### 浏览器功能(Playwright)

Mini Browser 和浏览器自动化使用 Playwright 的 Chromium。即使它下载失败,CraftBot 的其余功能仍可正常使用。之后重新运行 `python craftbot.py install` 即可重试。

---

## 🐳 使用容器运行

Docker 镜像以浏览器模式运行 CraftBot,所需组件均已预装:Python 3.10 及其锁定的依赖、Node.js 24、浏览器界面、PocketBase 和 Playwright 的 Chromium。

在仓库根目录执行:

```bash
docker compose up -d
```

首次构建需要几分钟。之后打开 http://localhost:7925,在引导流程中填写你的 LLM API 密钥。

设置与 API 密钥、Agent 文件、记忆和日志都保存在 `craftbot-data` 卷中,重启容器或重新构建镜像后依然保留。

```bash
docker compose logs -f craftbot              # 实时查看日志
docker compose ps                            # 查看状态(含健康检查)
docker compose down                          # 停止(数据卷会保留)
git pull && docker compose up -d --build     # 更新到最新版本
```

- 端口只发布在 `127.0.0.1` 上,因为 CraftBot 界面本身没有登录机制。在远程服务器上请保持这一设置,并通过“故障排查”中介绍的 SSH 隧道连接。主机端口请保持为 7925 和 7926:CraftBot 只接受以 `localhost` 访问这两个端口的浏览器连接。
- 在 shell 或 `docker-compose.yml` 同目录下的 `.env` 文件中设置的代理和镜像变量(`HTTPS_PROXY`、`PIP_INDEX_URL`、`HF_ENDPOINT`、`CRAFTBOT_MIRRORS` 以及 `.env.example` 中列出的其他变量)会传入容器。
- Agent App 在容器内的 3100 至 3199 端口运行,目前还无法从主机浏览器打开。如需使用 Agent App,请使用安装程序或源码安装。
- 不使用 Compose 时:
  ```bash
  docker build -t craftbot .
  docker run -d --name craftbot -p 127.0.0.1:7925:7925 -p 127.0.0.1:7926:7926 --shm-size 1g -v craftbot-data:/data craftbot
  ```

---

## 🤝 如何参与贡献

欢迎提交 PR!工作流(fork → 从 `dev` 创建分支 → 提 PR)详见 [CONTRIBUTING.md](CONTRIBUTING.md)。所有 PR 都会自动跑 lint + 冒烟测试 CI。

> [!IMPORTANT]
> **CraftBot** 仍在积极开发中,每周都有改进。如果有问题或希望更快交流,欢迎加入 [Discord](https://discord.gg/ZN9YHc37HG),或发邮件至 thamyikfoong(at)craftos.net。

---

## 🧾 许可证

本项目基于 [MIT License](LICENSE) 开源。你可以自由地使用、托管以及商业化运营本项目(如果用于分发或商业化,需要保留对本项目的署名)。

---

## ⭐ 致谢

由 [CraftOS](https://craftos.net/) 及贡献者共同开发与维护。  
如果你觉得 **CraftBot** 有帮助,欢迎给仓库点 ⭐ 并分享给身边的人!

---

## Star 历史

<a href="https://star-history.dera.page/#CraftOS-dev/CraftBot&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
 </picture>
</a>
