<div align="center">
    <img src="assets/craftbot_logo_text_small.png" alt="CraftBot" width="400"/>
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
  <a href="README.md">English</a> | <a href="README.ja.md">日本語</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ko.md">한국어</a> | <a href="README.es.md">Español</a> | <a href="README.pt-BR.md">Português</a> | <a href="README.fr.md">Français</a> | <a href="README.de.md">Deutsch</a>
</p>

<div align="center">
    <img src="assets/README_banner.png" alt="CraftBot Banner" width="1280"/>
</div>

## ✨ 核心特性

除了能够创建并运行自有 SaaS 工具,CraftBot 还具备 Agent 框架的全部核心能力,可以作为一个通用 AI Agent 陪你处理任务、工具、记忆与日常工作流。

- **Agent 配置档案** 40+ Agent 配置档案(CEO Agent、财务 Agent、市场负责人 Agent、DevOps 工程师、视频制作 Agent 等共 37 种)随时为你服务。从 **[CraftBot Agent Bundles](https://github.com/CraftOS-dev/craftbot-agent-bundles)** 找到所需角色,一键导入。
- **Playbook 目录** 不知道如何用 AI Agent 自动化?CraftBot 内置 120 个 Playbook(覆盖 19 个分类)随时可用。从顶部栏打开 Playbook 选择器,挑选一个 Playbook,它就会开始为你执行任务。
- **Living UI.** 在 CraftBot 内部构建、导入或演进自定义应用。Agent 始终感知 UI 状态,并能直接读取、写入和操作其中的数据。
- **多任务与会话路由.** 还在手动敲 `/new` 吗?CraftBot 能自行判断何时开启新会话、何时继续旧任务,让对话与上下文保持统一。
- **自托管与 BYOK.** 灵活的 LLM 提供商体系,支持 OpenAI、Google Gemini、Anthropic Claude、OpenRouter 等。也可以用 Ollama 自行托管模型,实现零 Token 消耗。
- **记忆系统.** 通过 RAG + Agent 文件系统 + 蒸馏,从你与 CraftBot 的交互中构建本地知识库。CraftBot 会在午夜「做梦」,整合一整天发生的事件。
- **主动型 Agent.** 学习你的偏好、习惯和人生目标,然后主动进行规划并发起任务(当然要经过你的同意),帮你在生活中变得更好。
- **外部工具集成.** 连接你的应用,例如 Google Workspace、Slack、Notion、Zoom、LinkedIn、Discord、Telegram 等(还有更多正在路上),支持 OAuth 或使用你自己的密钥。
- **Skills 与 MCP.** 已就绪 150+ MCP 与 170+ Skills,支持快速安装新的 Skills 与 MCP,也可以从已完成的任务中一键创建或改进 Skills。
- **浏览器界面与 CLI 支持.** 用最适合你的方式使用 CraftBot:日常使用走简洁的浏览器 UI,脚本和无界面环境则可以走 CLI。

---


## 🧰 环境设置

### 前置要求
- Python **3.10+**
- `git`（克隆仓库所需）
- 你所选 LLM 提供商的 API Key（OpenAI、Gemini 或 Anthropic）
- `Node.js` **18+**（可选 - 仅浏览器界面需要）
- `conda`（可选 - 如未找到，安装器会提供自动安装 Miniconda 的选项）

### 我该选哪种方式？

> **不确定？选方案一。** 它会帮你搞定所有事。

| | 方案一 — 服务安装 | 方案二 — Conda 安装 | 方案三 — 手动安装 |
|---|---|---|---|
| **适合谁** | 大多数用户、新手、测试 | 想要独立环境的 Conda 用户 | 进阶用户、自定义 Python、完全控制 |
| **自动管理 Python 环境？** | ✅ 自动 | ✅ 自动 | ❌ 你自己管理 |
| **后台运行？** | ✅ 是，作为服务 | ❌ 否 | ❌ 否 |
| **启动方式** | `python craftbot.py install` | `python install.py --conda` | `python install.py` |

---

### ⭐ 方案一 — 服务安装（推荐）

**适合你，如果：** 你希望 CraftBot 开箱即用——后台服务、开机自启、桌面快捷方式，无需手动操作。

`craftbot.py` 全程自动处理：Python 环境、依赖安装、后台进程管理和自启注册。

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

## 🌱 Living UI

**Living UI 是会随你的需求一同演进的系统/应用/仪表盘。**

<div align="center">
    <img src="assets/living_ui_banner.gif" alt="CraftBot Banner" width="1280"/>
</div>

- 想要一个内置 AI 协作伙伴的看板?
- 一套完全贴合你工作流的定制 CRM?
- 一个 CraftBot 能替你读取并操作的公司仪表盘?

```bash
# 1. 克隆仓库
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. 安装到 conda 环境
python install.py --conda

# 3. 运行 CraftBot
conda run -n craftbot python run.py

# 如果 conda 不在 PATH 中（仅 Windows）：
&"$env:USERPROFILE\miniconda3\Scripts\conda.exe" run -n craftbot python run.py
```

> [!NOTE]
> 每次运行 CraftBot 时，请使用 `conda run -n craftbot python run.py`。此方式没有后台服务——由你手动启停。

---

### 方案三 — 手动安装（pip）

**适合你，如果：** 你希望完全掌控 Python 环境，不需要任何自动服务或后台进程，自己管理 CraftBot。

`install.py`（不带参数）会对当前激活的 Python 环境执行标准 pip 安装。通过 `run.py` 手动启停 CraftBot。

```bash
# 1. 克隆仓库
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. 在当前 Python 环境中安装依赖
python install.py

# 3. 运行 CraftBot
python run.py
```

首次运行会引导你完成 API Key 设置和偏好配置。

> [!NOTE]
> 如果未安装 Node.js，安装器会提供详细指引。你也可以完全跳过浏览器模式，直接使用 CLI 模式——无需 Node.js：`python run.py --cli`

### 安装完成后你可以做什么？
- 用自然语言与代理交流
- 让它执行复杂的多步骤任务
- 输入 `/help` 查看可用命令
- 连接 Google、Slack、Notion 等服务

### 🖥️ 界面模式

<div align="center">
    <img src="assets/WCA_README_banner.png" alt="CraftOS Banner" width="1280"/>
</div>

CraftBot 支持多种 UI 模式。根据你的偏好选择：

| 模式 | 命令 | 要求 | 最适合 |
|------|---------|--------------|----------|
| **浏览器** | `python run.py` | Node.js 18+ | 现代 Web 界面，最易使用 |
| **CLI** | `python run.py --cli` | 无 | 命令行，轻量级 |

**浏览器模式**是默认的推荐模式。如果你没有 Node.js，安装器会提供安装指引，或者你可以使用 **CLI 模式**。

---

## 🧬 Living UI

**Living UI 是随你需求而进化的系统/应用/仪表盘。**

需要一个内置 AI 副驾的看板？量身定制符合你工作流程的 CRM？
一个 CraftBot 能读取并驱动的公司仪表盘？
将它作为 Living UI 启动——它与 CraftBot 并行运行，并随着你的需求变化而成长。

<div align="center">
    <img src="assets/living-ui-example.png" alt="Living UI example" width="1280"/>
</div>

### 创建 Living UI 的三种方式

1. **从零构建.** 用自然语言描述你想要的东西,CraftBot 会搭好数据模型、后端 API 和 React 前端,并通过一套结构化的设计流程与你不断迭代。

<div align="center">
    <img src="assets/living-ui-custom-build.png" alt="Building a Living UI from scratch" width="448"/>
</div>

2. **从市场安装.** 在 [living-ui-marketplace](https://github.com/CraftOS-dev/living-ui-marketplace) 中浏览社区构建的 Living UI。

<div align="center">
    <img src="assets/living-ui-marketplace.png" alt="Living UI marketplace" width="448"/>
</div>

3. **导入现有项目.** 把 Go、Node.js、Python、Rust 或者静态源码、GitHub 仓库交给 CraftBot,它会自动识别运行时、配置健康检查,并把它封装成一个 Living UI。

<div align="center">
    <img src="assets/living-ui-import.png" alt="Importing an existing project as a Living UI" width="448"/>
</div>

### 让 Agent 持续参与的不断演进

Living UI 永远没有「完成」这一说。需求一变,就让 Agent 给它加功能、改版页面或接入新数据源。

CraftBot 嵌入在每个 Living UI 之中,并且**对其状态保持感知**:它可以读取当前 DOM 和表单值、通过 REST API 查询应用数据,并代替你触发操作。

### 让 SaaS 工具保持开放与鲜活

构建、定制并不断演进属于自己的 Living UI,减少对那些从未真正为你量身定制的订阅工具的依赖。

我们正在积极寻找愿意展示自己 Living UI 的开发者,并支持将它们导出到 **[Living UI 市场](https://craftos.net/marketplace)**。欢迎提交 PR!

---
 
# 三个 5 分钟内可以试玩的 Living UI
 
- **📋 看板** — 把所有任务、跟进事项和待办集中到一个地方,CraftBot 可以接手运营,替你完成 PM 工作。
- **📊 习惯追踪器** — 培养并追踪自己的习惯,用类 GitHub 风格的活动日历像写代码一样维护你的习惯。
- **🐦 Luolinglo** — 不是多邻国,但你可以学习新语言、做单词卡片,并和 CraftBot 一起练习。

## 🧩 架构概览

| 组件 | 说明 |
|-----------|-------------|
| **代理基础层 (Agent Base)** | 核心编排层，管理任务生命周期、协调各组件并处理主要的代理循环。 |
| **LLM 接口** | 统一接口，支持多个 LLM 提供商（OpenAI、Gemini、Anthropic、BytePlus、Ollama）。 |
| **上下文引擎** | 生成优化的提示词，支持 KV-cache。 |
| **动作管理器** | 从动作库中检索和执行动作。自定义动作易于扩展。 |
| **动作路由器** | 根据任务需求智能选择最佳匹配的动作，需要时通过 LLM 解析输入参数。 |
| **事件流** | 实时事件发布系统，用于任务进度跟踪、UI 更新和执行监控。 |
| **记忆管理器** | 基于 RAG 的语义记忆，使用 ChromaDB。处理记忆分块、向量化、检索和增量更新。 |
| **状态管理器** | 全局状态管理，跟踪代理执行上下文、对话历史和运行时配置。 |
| **任务管理器** | 管理任务定义，支持简单和复杂任务模式，创建待办事项，多步骤工作流跟踪。 |
| **技能管理器** | 加载并将可插拔技能注入代理上下文。 |
| **MCP 适配器** | 模型上下文协议集成，将 MCP 工具转换为原生动作。 |

---
 
# CraftBot 与其他方案的对比
 
|                                  | v0 / Lovable / Bolt | OpenClaw | Claude Code | **CraftBot**                            |
| -------------------------------- | ------------------- | -------------------- | -------------------- | --------------------------------------- |
| **构建自定义应用**           | ✅ 一次性生成         | 🚫                   | ✅ (手动)          | ✅ 对话式持续构建                       |
| **Agent 能操作应用**       | 🚫                  | ⚠️ 通过工具调用      | 🚫                   | ✅ 内置于每个 Living UI         |
| **持久化的 Agent 记忆**      | 🚫                  | ✅            | ✅                   | ✅ RAG + Agent 文件系统 + 蒸馏        |
| **自托管**     | ⚠️ 部分支持         | ✅                   | 🚫 SaaS              | ✅ MIT 协议,运行在你自己的机器上                    |
| **模型无关**     | ✅         | ✅                   | ⚠️ 部分支持              | ✅ 主流厂商 + OpenRouter                    |
 
---

## 🔧 故障排查与常见问题

### install.py

| 参数 | 说明 |
|------|-------------|
| `--conda` | 使用 conda 环境（可选） |

### run.py

| 参数 | 说明 |
|------|-------------|
| （无） | 以**浏览器**模式运行（推荐，需要 Node.js） |
| `--cli` | 以 **CLI** 模式运行（轻量级） |

**安装示例：**
```bash
# 简单 pip 安装（不使用 conda）
python install.py

# 使用 conda 环境（推荐 conda 用户使用）
python install.py --conda
```

**运行 CraftBot：**

```powershell
# 浏览器模式（默认，需要 Node.js）
python run.py

# CLI 模式（轻量级）
python run.py --cli

# 使用 conda 环境
conda run -n craftbot python run.py

# 如果 conda 不在 PATH 中，使用完整路径
&"$env:USERPROFILE\miniconda3\Scripts\conda.exe" run -n craftbot python run.py
```

**Linux/macOS (Bash):**
```bash
# 浏览器模式（默认，需要 Node.js）
python run.py

# CLI 模式（轻量级）
python run.py --cli

# 使用 conda 环境
conda run -n craftbot python run.py
```

### 🔧 后台服务（推荐）

将 CraftBot 作为后台服务运行，关闭终端后仍可继续运行。系统会自动创建桌面快捷方式，随时可重新打开浏览器。

```bash
# 安装依赖、注册开机自启、启动 CraftBot
python craftbot.py install
```

就这样。终端会自动关闭，CraftBot 在后台运行，浏览器自动打开。

```bash
# 其他服务命令：
python craftbot.py start    # 在后台启动 CraftBot
python craftbot.py status   # 检查是否正在运行
python craftbot.py stop     # 停止 CraftBot
python craftbot.py restart  # 重启 CraftBot
python craftbot.py logs     # 查看最近日志输出
```

| 命令 | 说明 |
|---------|-------------|
| `python craftbot.py install` | 安装依赖、注册开机自启、启动 CraftBot、打开浏览器，并自动关闭终端 |
| `python craftbot.py start` | 在后台启动 CraftBot（若已运行则自动重启，终端自动关闭） |
| `python craftbot.py stop` | 停止 CraftBot |
| `python craftbot.py restart` | 停止并重启 CraftBot |
| `python craftbot.py status` | 检查 CraftBot 是否在运行，以及自动启动是否已启用 |
| `python craftbot.py logs` | 显示最近日志（使用 `-n 100` 查看更多行） |
| `python craftbot.py uninstall` | 停止 CraftBot、注销自启、卸载 pip 包并清理 pip 缓存 |

> [!TIP]
> 执行 `craftbot.py start` 或 `craftbot.py install` 后，系统会自动创建 **CraftBot 桌面快捷方式**。如果不小心关闭了浏览器，双击快捷方式即可重新打开。

> [!NOTE]
> **安装：** 安装器会在缺少依赖时提供清晰的指引。如果未找到 Node.js，会提示你安装或切换到 CLI 模式。安装会自动检测 GPU 可用性，必要时回退到仅 CPU 模式。

> [!TIP]
> **首次设置：** CraftBot 会引导你完成引导流程，配置 API Key、代理名称、MCP 和技能。

> [!NOTE]
> **Playwright Chromium：** WhatsApp Web 集成可选。如果安装失败，代理在其他任务上仍能正常工作。可稍后手动安装：`playwright install chromium`

---

## 🔧 故障排除与常见问题

### 缺少 Node.js（浏览器模式）
运行 `python run.py` 时看到 **"npm not found in PATH"**：
1. 从 [nodejs.org](https://nodejs.org/) 下载（选择 LTS 版本）
2. 安装并重启终端
3. 再次运行 `python run.py`

**替代方案：** 使用 CLI 模式（不需要 Node.js）：
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
