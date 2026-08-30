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
- **浏览器界面与 CLI 支持.** 用最适合你的方式使用 CraftBot:日常使用走简洁的浏览器 UI,脚本和无界面环境则可以走 CLI。

---


## 🧰 快速开始

环境要求:Python 3.10+ · 浏览器模式需要 Node.js 18+

```bash
# 1. 克隆仓库
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. 安装、注册自启动并运行 CraftBot
python craftbot.py install
```

就这么简单。终端会自动关闭,CraftBot 在后台运行,浏览器自动打开。同时还会创建一个**桌面快捷方式**,方便你随时重新打开浏览器。

**安装完成后管理服务:**

```bash
python craftbot.py start      # 在后台启动 CraftBot
python craftbot.py stop       # 停止 CraftBot
python craftbot.py restart    # 重启 CraftBot
python craftbot.py status     # 查看运行状态以及是否已启用自启动
python craftbot.py logs       # 查看近期日志输出
python craftbot.py uninstall  # 停止运行、移除自启动并卸载所有依赖包
```

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

### 缺少 Node.js(浏览器模式)
运行 `python run.py` 时看到 **"npm not found in PATH"**:
1. 从 [nodejs.org](https://nodejs.org/) 下载(选择 LTS 版本)
2. 安装并重启终端
3. 再次运行 `python run.py`

**替代方案:** 使用 CLI 模式(不需要 Node.js):
```bash
python run.py --cli
```

### 安装时依赖失败
安装器现在会提供更详细的错误信息和解决方案。如果安装失败:
- **检查 Python 版本:** 确认已安装 Python 3.10+ (`python --version`)
- **检查网络连接:** 安装过程中需要下载依赖
- **清理 pip 缓存:** 运行 `pip install --upgrade pip` 后再次尝试

### Playwright 安装失败
Playwright Chromium 的安装是可选项。即使失败:
- Agent 在执行其他任务时**仍可正常工作**
- 可以先跳过,稍后再用 `playwright install chromium` 安装
- 仅在使用 WhatsApp Web 集成时才需要

更详细的排查请参阅 [INSTALLATION_FIX.md](INSTALLATION_FIX.md)。

---
## 🐳 使用容器运行

仓库根目录包含一份 Docker 配置,内含 Python 3.10、关键系统包(包括用于 OCR 的 Tesseract)以及 `environment.yml`/`requirements.txt` 中定义的所有 Python 依赖,确保 Agent 在隔离环境中也能稳定运行。

下面是用容器运行 Agent 的步骤。

### 构建镜像

在仓库根目录执行:

```bash
docker build -t craftbot .
```

### 运行容器

镜像默认以 `python -m app.main` 启动 Agent。如需交互式运行:

```bash
docker run --rm -it craftbot
```

需要传入环境变量时,可以挂载一个 env 文件(例如基于 `.env.example`):

```bash
docker run --rm -it --env-file .env craftbot
```

通过 `-v` 挂载需要持久化到容器外的目录(例如数据或缓存目录),并根据你的部署需求调整端口或其他参数。镜像内置了 OCR(`tesseract`)所需的系统依赖和常见的 HTTP 客户端,让 Agent 可以直接在容器内处理文件和网络 API。

镜像默认使用 Python 3.10,并已打包好 `environment.yml`/`requirements.txt` 中的依赖,因此 `python -m app.main` 开箱即用。

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
