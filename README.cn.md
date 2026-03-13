
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
    <img src="https://img.shields.io/badge/Discord-%E5%8A%A0%E5%85%A5%E7%A4%BE%E5%8C%BA-5865F2?logo=discord&logoColor=white" alt="Discord">
  </a>
<br/>
<br/>

[![SPONSORED BY E2B FOR STARTUPS](https://img.shields.io/badge/SPONSORED%20BY-E2B%20FOR%20STARTUPS-ff8800?style=for-the-badge)](https://e2b.dev/startups)
</div>

<p align="center">
  <a href="README.md"> English README</a> | <a href="README.ja.md"> 日本語版はこちら</a>
</p>

## 🚀 概览
<h3 align="center">
CraftBot 是你的个人 AI 助手，它驻留在你的设备中，全天候为你服务。
</h3>

它能够自主理解任务、规划行动并执行操作，以实现你的目标。
它会学习你的偏好和目标，主动帮助你规划并启动任务，以实现你的人生目标。
支持 MCP、技能以及外部应用集成。

CraftBot 静候你的指令，现在就部署属于你的 CraftBot 吧。

---

## ✨ 特性

- **自带密钥 (BYOK)** — 灵活的 LLM 提供商系统，支持 OpenAI、Google Gemini、Anthropic Claude、BytePlus 和本地 Ollama 模型。可轻松切换提供商。
- **记忆系统** — 在午夜整理并汇总一天中发生的事件。
- **主动式代理** — 学习你的偏好、习惯和人生目标，然后进行规划并启动任务（当然需要你的批准）来帮助你改善生活。
- **外部工具集成** — 连接 Google Workspace、Slack、Notion、Zoom、LinkedIn、Discord 和 Telegram（更多即将推出！），支持嵌入式凭据和 OAuth。
- **MCP** — 模型上下文协议（Model Context Protocol）集成，通过外部工具和服务扩展代理能力。
- **技能系统** — 可扩展的技能框架，内置任务规划、研究、代码审查、Git 操作等技能。
- **跨平台** — 完整支持 Windows 和 Linux，具有平台特定代码变体和 Docker 容器化。

> [!IMPORTANT]
> **关于 GUI 模式的说明：** GUI 模式仍处于实验阶段。代理切换到 GUI 模式时可能会遇到一些问题。我们正在积极改进此功能。

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

### 快速安装

```bash
# 克隆仓库
git clone https://github.com/zfoong/CraftBot.git
cd CraftBot

# 安装依赖
python install.py

# 运行代理
python run.py
```

就这样！首次运行会引导你设置 API Key。

**注意：** 如果你没有安装 Node.js，安装器会提供详细的安装指引。你也可以跳过浏览器模式，改用 TUI（见下方模式说明）。

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
| **TUI** | `python run.py --tui` | 无 | 终端 UI，无需额外依赖 |
| **CLI** | `python run.py --cli` | 无 | 命令行，轻量级 |
| **GUI** | `python run.py --gui` | `install.py --gui` | 带视觉反馈的桌面自动化 |

**浏览器模式**是默认的推荐模式。如果你没有 Node.js，安装器会提供安装指引，或者你可以使用 **TUI 模式**。

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
| **TUI 界面** | 基于 Textual 框架构建的终端用户界面，用于交互式命令行操作。 |
| **GUI 模块** | 实验性 GUI 自动化，使用 Docker 容器、OmniParser 进行 UI 元素检测，以及 Gradio 客户端。 |

---

## 🔜 路线图

- [X] **记忆模块** — 已完成。
- [ ] **外部工具集成** — 持续添加中！
- [X] **MCP 层** — 已完成。
- [X] **技能层** — 已完成。
- [X] **主动式行为** — 待定

---

## 🖥️ GUI 模式（可选）

GUI 模式支持屏幕自动化 - 代理可以看到并与桌面环境交互。这是可选的，需要额外设置。

```bash
# 安装 GUI 支持（使用 pip，不需要 conda）
python install.py --gui

# 使用 GUI 支持和 conda 安装
python install.py --gui --conda

# 以 GUI 模式运行
python run.py --gui
```

> [!NOTE]
> GUI 模式是实验性功能，需要额外的依赖（约 4GB 模型权重）。如果你不需要桌面自动化，请跳过此项，使用 Browser/TUI 模式即可，无需额外依赖。

---

## 📋 命令参考

### install.py

| 参数 | 说明 |
|------|-------------|
| `--gui` | 安装 GUI 组件（OmniParser） |
| `--conda` | 使用 conda 环境（可选） |
| `--cpu-only` | 安装仅 CPU 版本的 PyTorch（与 --gui 一起使用） |

### run.py

| 参数 | 说明 |
|------|-------------|
| （无） | 以**浏览器**模式运行（推荐，需要 Node.js） |
| `--tui` | 以**终端 UI** 模式运行（无需额外依赖） |
| `--cli` | 以 **CLI** 模式运行（轻量级） |
| `--gui` | 启用 GUI 自动化模式（需先运行 `install.py --gui`） |

**安装示例：**
```bash
# 简单 pip 安装（不使用 conda）
python install.py

# 带 GUI 支持（使用 pip，不需要 conda）
python install.py --gui

# 仅 CPU 系统上的 GUI（使用 pip，不需要 conda）
python install.py --gui --cpu-only

# 使用 conda 环境（推荐 conda 用户使用）
python install.py --conda

# GUI 支持和 conda
python install.py --gui --conda

# 使用 conda 的仅 CPU 系统上的 GUI
python install.py --gui --conda --cpu-only
```

**运行 CraftBot：**

```powershell
# 浏览器模式（默认，需要 Node.js）
python run.py

# TUI 模式（不需要 Node.js）
python run.py --tui

# CLI 模式（轻量级）
python run.py --cli

# GPU/GUI 模式
python run.py --gui

# 使用 conda 环境
conda run -n craftbot python run.py

# 如果 conda 不在 PATH 中，使用完整路径
&"$env:USERPROFILE\miniconda3\Scripts\conda.exe" run -n craftbot python run.py
```

**Linux/macOS (Bash):**
```bash
# 浏览器模式（默认，需要 Node.js）
python run.py

# TUI 模式（不需要 Node.js）
python run.py --tui

# CLI 模式（轻量级）
python run.py --cli

# GPU/GUI 模式
python run.py --gui

# 使用 conda 环境
conda run -n craftbot python run.py
```

> [!NOTE]
> **安装：** 安装器会在缺少依赖时提供清晰的指引。如果未找到 Node.js，会提示你安装或切换到 TUI 模式。安装会自动检测 GPU 可用性，必要时回退到仅 CPU 模式。

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

**替代方案：** 使用 TUI 模式（不需要 Node.js）：
```bash
python run.py --tui
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

### GPU/CUDA 问题
安装器会自动检测 GPU 可用性：
- 如果 CUDA 安装失败，会自动回退到 CPU 模式
- 手动 CPU 设置：`python install.py --gui --cpu-only`

详细故障排除，请参阅 [INSTALLATION_FIX.md](INSTALLATION_FIX.md)。

---

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
## 使用容器运行

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

使用 `-v` 挂载需要在容器外持久化的目录（例如数据或缓存文件夹），并根据部署需要调整端口或额外参数。该容器内置 OCR（`tesseract`）、屏幕自动化（`pyautogui`、`mss`、X11 工具与虚拟帧缓冲）以及常见 HTTP 客户端等系统依赖，使代理能够在容器中处理文件、网络 API 与 GUI 自动化。

### 启用 GUI/屏幕自动化

GUI 操作（鼠标/键盘事件、截图）需要 X11 服务器。你可以连接宿主机显示，或使用 `xvfb` 无头运行：

* 使用宿主机显示（需要带 X11 的 Linux）：

  ```bash
  docker run --rm -it
    -e DISPLAY=$DISPLAY \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v $(pwd)/data:/app/app/data \
    craftbot
  ```

  如需让代理读写更多目录，可添加额外的 `-v` 挂载。

* 使用虚拟显示进行无头运行：

  ```bash
	docker run --rm -it --env-file .env craftbot bash -lc "Xvfb :99 -screen 0 1920x1080x24 & export DISPLAY=:99 && exec python -m app.main"
  ```

默认情况下镜像会使用 Python 3.10，并打包了 `environment.yml`/`requirements.txt` 中的 Python 依赖，因此 `python -m app.main` 可开箱即用。

---

## 🤝 如何贡献

欢迎各种建议与反馈！你可以联系 [@zfoong](https://github.com/zfoong)，邮箱为 thamyikfoong(at)craftos.net。我们目前尚未配置检查流程，因此无法接受直接提交贡献，但非常感谢你的建议与反馈。

## 🧾 许可证

本项目采用 [MIT License](LICENSE) 许可。你可以自由使用、部署并将其商业化（在分发与商业化时必须注明本项目来源）。

---

## ⭐ 致谢

由 [CraftOS](https://craftos.net/) 与贡献者 [@zfoong](https://github.com/zfoong) 及 [@ahmad-ajmal](https://github.com/ahmad-ajmal) 开发与维护。
如果你觉得 **CraftBot** 有用，请给仓库点一个 ⭐ 并分享给更多人！
