
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
    <img src="https://img.shields.io/badge/Discord-%E5%8A%A0%E5%85%A5%E7%A4%BE%E5%8C%BA-5865F2?logo=discord&logoColor=white" alt="Discord">
  </a>
<br/>
<br/>

[![SPONSORED BY E2B FOR STARTUPS](https://img.shields.io/badge/SPONSORED%20BY-E2B%20FOR%20STARTUPS-ff8800?style=for-the-badge)](https://e2b.dev/startups)

<a href="https://www.producthunt.com/products/craftbot?embed=true&amp;utm_source=badge-top-post-badge&amp;utm_medium=badge&amp;utm_campaign=badge-craftbot" target="_blank" rel="noopener noreferrer"><img alt="CraftBot - Self-hosted proactive AI assistant that lives locally | Product Hunt" width="250" height="54" src="https://api.producthunt.com/widgets/embed-image/v1/top-post-badge.svg?post_id=1110300&amp;theme=dark&amp;period=daily&amp;t=1776679679509"></a>
</div>

<p align="center">
  <a href="README.md">English</a> | <a href="README.ja.md">日本語</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ko.md">한국어</a> | <a href="README.es.md">Español</a> | <a href="README.pt-BR.md">Português</a> | <a href="README.fr.md">Français</a> | <a href="README.de.md">Deutsch</a>
</p>

## 🚀 概览
<h3 align="center">
CraftBot 是你的个人 AI 助手，它驻留在你的设备中，全天候为你服务。
</h3>

它能够自主理解任务、规划行动并执行操作，以实现你的目标。
它会学习你的偏好和目标，主动帮助你规划并启动任务，以实现你的人生目标。
支持 MCP、技能以及外部应用集成。

CraftBot 静候你的指令，现在就部署属于你的 CraftBot 吧。

<div align="center">
    <img src="assets/craftbot_overview.png" alt="CraftBot Overview" width="1280"/>
</div>

---

## ✨ 特性

- **自带密钥 (BYOK)** — 灵活的 LLM 提供商系统，支持 OpenAI、Google Gemini、Anthropic Claude、BytePlus 和本地 Ollama 模型。可轻松切换提供商。
- **记忆系统** — 在午夜整理并汇总一天中发生的事件。
- **主动式代理** — 学习你的偏好、习惯和人生目标，然后进行规划并启动任务（当然需要你的批准）来帮助你改善生活。
- **Living UI** — 在 CraftBot 中构建、导入或演进自定义应用。代理始终感知 UI 的状态，并可直接读取、写入和操作其数据。
- **外部工具集成** — 连接 Google Workspace、Slack、Notion、Zoom、LinkedIn、Discord 和 Telegram（更多即将推出！），支持嵌入式凭据和 OAuth。
- **MCP** — 模型上下文协议（Model Context Protocol）集成，通过外部工具和服务扩展代理能力。
- **技能系统** — 可扩展的技能框架，内置任务规划、研究、代码审查、Git 操作等技能。
- **跨平台** — 完整支持 Windows、macOS 和 Linux，具有平台特定代码变体和 Docker 容器化。

> [!IMPORTANT]
> **GUI 模式已弃用。** CraftBot 不再支持 GUI（桌面自动化）模式。请改用 Browser 或 CLI 模式。

<div align="center">
    <img src="assets/craftbot_readme_features.png" alt="CraftBot Banner" width="1280"/>
	<img src="assets/craftbot_features_custom.png" alt="CraftBot Banner" width="1280"/>
</div>

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

# 2. 安装、注册自启并启动 CraftBot
python craftbot.py install
```

就这样。终端自动关闭，CraftBot 在后台运行，浏览器自动打开。同时会创建**桌面快捷方式**，随时可重新打开浏览器。

**安装后的服务管理命令：**

```bash
python craftbot.py start      # 在后台启动 CraftBot
python craftbot.py stop       # 停止 CraftBot
python craftbot.py restart    # 重启 CraftBot
python craftbot.py status     # 检查是否运行，自启是否已启用
python craftbot.py logs       # 查看最近日志
```

> [!TIP]
> 执行 `install` 或 `start` 后，系统会自动创建 **CraftBot 桌面快捷方式**。如果关闭了浏览器，双击快捷方式即可重新打开。

---

### 方案二 — Conda 安装

**适合你，如果：** 你已经在使用 conda，希望 CraftBot 运行在独立的 conda 环境中。

`install.py --conda` 会创建专用的 `craftbot` conda 环境。若系统中未找到 Miniconda，会自动安装。

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

1. **从零开始构建。** 用自然语言描述你想要的。CraftBot 会搭建
   数据模型、后端 API 和 React UI，并通过结构化的设计流程
   与你一起迭代。

<div align="center">
    <img src="assets/living-ui-custom-build.png" alt="Building a Living UI from scratch" width="448"/>
</div>

2. **从市场安装。** 从 [living-ui-marketplace](https://github.com/CraftOS-dev/living-ui-marketplace) 浏览社区构建的 Living UI。

<div align="center">
    <img src="assets/living-ui-marketplace.png" alt="Living UI marketplace" width="448"/>
</div>

3. **导入已有项目。** 将 CraftBot 指向 Go、Node.js、Python、Rust 或静态源代码
   或 GitHub 仓库。它会检测运行时、配置健康检查，并将其封装为 Living UI。

<div align="center">
    <img src="assets/living-ui-import.png" alt="Importing an existing project as a Living UI" width="448"/>
</div>

### 让 CraftBot 融入其中，持续进化

Living UI 永远不会"完成"。随着你的需求增长，你可以让代理添加功能、
重新设计视图或将其接入新的数据源。

CraftBot 嵌入在每个 Living UI 中，并**感知其状态**：
它可以读取当前的 DOM 和表单值，通过 REST API 查询应用数据，
并代表你触发操作。

---

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

## 🔜 路线图

- [X] **记忆模块** — 已完成。
- [ ] **外部工具集成** — 持续添加中！
- [X] **MCP 层** — 已完成。
- [X] **技能层** — 已完成。
- [ ] **主动式行为** — 待定

---

## 📋 命令参考

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

### 依赖安装失败
安装器会提供带解决方案的详细错误信息。如果安装失败：
- **检查 Python 版本：** 确保是 Python 3.10+（`python --version`）
- **检查网络连接：** 安装期间会下载依赖
- **清除 pip 缓存：** 运行 `pip install --upgrade pip` 然后重试

### Playwright 安装问题
Playwright chromium 安装是可选的。如果失败：
- 代理在其他任务上**仍能正常工作**
- 可跳过或稍后安装：`playwright install chromium`
- 仅 WhatsApp Web 集成需要

详细故障排除，请参阅 [INSTALLATION_FIX.md](INSTALLATION_FIX.md)。

---

## 🔌 外部服务集成

代理可以使用 OAuth 连接各种服务。正式版本附带嵌入式凭据，但你也可以使用自己的凭据。

### 快速开始

对于附带嵌入式凭据的正式版本：
```
/google login    # 连接 Google Workspace
/zoom login      # 连接 Zoom
/slack invite    # 连接 Slack
/notion invite   # 连接 Notion
/linkedin login  # 连接 LinkedIn
```

### 服务详情

| 服务 | 认证类型 | 命令 | 需要密钥？ |
|---------|-----------|---------|------------------|
| Google | PKCE | `/google login` | 否 (PKCE) |
| Zoom | PKCE | `/zoom login` | 否 (PKCE) |
| Slack | OAuth 2.0 | `/slack invite` | 是 |
| Notion | OAuth 2.0 | `/notion invite` | 是 |
| LinkedIn | OAuth 2.0 | `/linkedin login` | 是 |

### 使用自己的凭据

如果你想使用自己的 OAuth 凭据，请将它们添加到 `.env` 文件中：

#### Google（PKCE - 仅需 Client ID）
```bash
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
```
1. 前往 [Google Cloud Console](https://console.cloud.google.com/)
2. 启用 Gmail、Calendar、Drive 和 People API
3. 创建 OAuth 凭据，类型选择 **桌面应用**
4. 复制 Client ID（PKCE 不需要密钥）

#### Zoom（PKCE - 仅需 Client ID）
```bash
ZOOM_CLIENT_ID=your-zoom-client-id
```
1. 前往 [Zoom Marketplace](https://marketplace.zoom.us/)
2. 创建 OAuth 应用
3. 复制 Client ID

#### Slack（需要两者）
```bash
SLACK_SHARED_CLIENT_ID=your-slack-client-id
SLACK_SHARED_CLIENT_SECRET=your-slack-client-secret
```
1. 前往 [Slack API](https://api.slack.com/apps)
2. 创建新应用
3. 添加 OAuth 范围：`chat:write`、`channels:read`、`users:read` 等
4. 复制 Client ID 和 Client Secret

#### Notion（需要两者）
```bash
NOTION_SHARED_CLIENT_ID=your-notion-client-id
NOTION_SHARED_CLIENT_SECRET=your-notion-client-secret
```
1. 前往 [Notion Developers](https://developers.notion.com/)
2. 创建新集成（公共集成）
3. 复制 OAuth Client ID 和 Secret

#### LinkedIn（需要两者）
```bash
LINKEDIN_CLIENT_ID=your-linkedin-client-id
LINKEDIN_CLIENT_SECRET=your-linkedin-client-secret
```
1. 前往 [LinkedIn Developers](https://developer.linkedin.com/)
2. 创建应用
3. 添加 OAuth 2.0 范围
4. 复制 Client ID 和 Client Secret

---
## 🐳 使用容器运行

仓库根目录包含 Docker 配置：使用 Python 3.10、关键系统依赖（包含用于 OCR 的 Tesseract），以及在 `environment.yml`/`requirements.txt` 中定义的所有 Python 库，从而让代理在隔离环境中保持一致运行。

下面是在容器中运行代理的配置步骤。

### 构建镜像

在仓库根目录执行：

```bash
docker build -t craftbot .
```

### 运行容器

镜像默认会用 `python -m app.main` 启动代理。要交互式运行：

```bash
docker run --rm -it craftbot
```

如果需要传入环境变量，可使用 env 文件（例如基于 `.env.example`）：

```bash
docker run --rm -it --env-file .env craftbot
```

使用 `-v` 挂载需要在容器外持久化的目录（例如数据或缓存文件夹），并根据部署需要调整端口或额外参数。该容器内置 OCR（`tesseract`）以及常见 HTTP 客户端等系统依赖，使代理能够在容器中处理文件与网络 API。

默认情况下镜像会使用 Python 3.10，并打包了 `environment.yml`/`requirements.txt` 中的 Python 依赖，因此 `python -m app.main` 可开箱即用。

---

## 🤝 如何贡献

欢迎提交 PR！请参阅 [CONTRIBUTING.md](CONTRIBUTING.md) 了解工作流程（fork → 从 `dev` 分支新建分支 → 提交 PR）。所有 Pull Request 都会自动运行 lint + 烟雾测试 CI。如需快速沟通，可加入我们的 [Discord](https://discord.gg/ZN9YHc37HG) 或发送邮件至 thamyikfoong(at)craftos.net。

## 🧾 许可证

本项目采用 [MIT License](LICENSE) 许可。你可以自由使用、部署并将其商业化（在分发与商业化时必须注明本项目来源）。

---

## ⭐ 致谢

由 [CraftOS](https://craftos.net/) 与贡献者 [@zfoong](https://github.com/zfoong) 及 [@ahmad-ajmal](https://github.com/ahmad-ajmal) 开发与维护。
如果你觉得 **CraftBot** 有用，请给仓库点一个 ⭐ 并分享给更多人！

---

## Star History

<a href="https://www.star-history.com/?repos=CraftOS-dev%2FCraftBot&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
 </picture>
</a>
