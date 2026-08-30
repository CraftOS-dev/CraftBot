<div align="center">
    <img src="assets/README_cover.png" alt="CraftBot" width="1280"/>
</div>

大多數 Agent 框架止步於對話和工具呼叫,CraftBot 走得更遠。它會自己建立、演進並運行 SaaS 工具,然後透過這套工具層與你溝通,並替你完成自動化工作。

除此之外,CraftBot 擁有通用 Agent 框架的全部核心能力。它像一位遠端員工一樣執行任務、記住你的偏好與目標,並主動協助你規劃並推進對你來說重要的事情。

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
  <a href="README.md">English</a> | <a href="README.ja.md">日本語</a> | <a href="README.cn.md">简体中文</a> | <a href="README.ko.md">한국어</a> | <a href="README.es.md">Español</a> | <a href="README.pt-BR.md">Português</a> | <a href="README.fr.md">Français</a> | <a href="README.de.md">Deutsch</a>
</p>

## ✨ 核心特色

除了能夠建立並運行自有的 SaaS 工具,CraftBot 還具備 Agent 框架的全部核心能力,可以作為通用 AI Agent 陪你處理任務、工具、記憶與日常工作流程。

- **Agent 設定檔** 40+ Agent 設定檔(CEO Agent、財務 Agent、行銷負責人 Agent、DevOps 工程師、影片製作人 Agent 等共 37 種)隨時準備為你工作。從 **[CraftBot Agent Bundles](https://github.com/CraftOS-dev/craftbot-agent-bundles)** 找到想要的角色,一鍵匯入。
- **Playbook 目錄** 不知道如何用 AI Agent 自動化?CraftBot 內建 120 個 Playbook(涵蓋 19 個分類)隨時可用。從頂部列開啟 Playbook 選擇器,挑一個 Playbook,它就會開始替你執行任務。
- **Agent App.** 在 CraftBot 內建立、匯入或演進自訂應用程式。Agent 隨時掌握 UI 的狀態,並能直接讀取、寫入並操作其中的資料。
- **多工與工作階段路由.** 還在手動輸入 `/new` 指令嗎?CraftBot 能自己判斷何時該開啟新會話、何時要繼續舊任務,讓對話與上下文保持一致。
- **自架與 BYOK.** 彈性的 LLM 供應商系統,支援 OpenAI、Google Gemini、Anthropic Claude、OpenRouter 等。也可以用 Ollama 自架模型,完全不耗 Token。
- **記憶系統.** 從你與 CraftBot 的互動中建立的第二大腦。混合方案:RAG + 知識圖譜 + Agent 檔案系統。CraftBot 會在午夜「做夢」,整合一整天發生的事件。
- **主動型 Agent.** 學習你的偏好、習慣與人生目標,然後主動規劃並發起任務(當然會徵求你的同意),協助你在生活中變得更好。
- **外部工具整合.** 連接你的應用,例如 Google Workspace、Slack、Notion、Zoom、LinkedIn、Discord、Telegram 等(更多正在路上),支援 OAuth 或使用你自己的金鑰。每個整合都可以連接多個帳號。
- **Skills 與 MCP.** 已備好 150+ MCP 與 170+ Skills,支援快速安裝新的 Skills 與 MCP,也能從已完成的任務一鍵建立或改進 Skills。
- **瀏覽器介面與 CLI 支援.** 選擇最適合你的方式使用 CraftBot:日常使用走簡潔的瀏覽器 UI,腳本與無介面環境則走 CLI。

---


## 🧰 快速開始

環境需求: Python 3.10+ · 瀏覽器模式需要 Node.js 18+

```bash
# 1. 複製儲存庫
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. 安裝、註冊自動啟動並執行 CraftBot
python craftbot.py install
```

就這麼簡單。終端機會自動關閉,CraftBot 會在背景執行,瀏覽器也會自動開啟。同時還會建立一個**桌面捷徑**,方便你隨時重新打開瀏覽器。

**安裝完成後管理服務:**

```bash
python craftbot.py start      # 在背景啟動 CraftBot
python craftbot.py stop       # 停止 CraftBot
python craftbot.py restart    # 重啟 CraftBot
python craftbot.py status     # 查看執行狀態以及是否已啟用自動啟動
python craftbot.py logs       # 查看最近的日誌輸出
python craftbot.py uninstall  # 停止執行、移除自動啟動並解除安裝相依套件
```

> [!TIP]
> 執行 `install` 或 `start` 之後,系統會自動建立 **CraftBot 桌面捷徑**。如果關閉了瀏覽器,雙擊捷徑即可重新打開。

---

## 🌱 Agent App

**Agent App 是會隨著你的需求一起演進的系統/應用/儀表板。**

<div align="center">
    <img src="assets/agent_app_banner.gif" alt="CraftBot Banner" width="1280"/>
</div>

- 想要一塊內建 AI 協作夥伴的 Kanban 看板?
- 一套完全貼合你工作流程的客製化 CRM?
- 一個 CraftBot 可以代替你讀取並操作的公司儀表板?

將它作為 Agent App 啟動:它會與 CraftBot 並行運作,並隨著你的需求變化而成長。

### 建立 Agent App 的三種方式

1. **從零開始建立.** 用自然語言描述你想要的東西,CraftBot
   會幫你搭好資料模型、後端 API 與 React 前端,
   並透過一套結構化的設計流程與你不斷迭代。

<div align="center">
    <img src="assets/agent-app-custom-build.png" alt="Building a Agent App from scratch" width="448"/>
</div>

2. **從市集安裝.** 在 [living-ui-marketplace](https://github.com/CraftOS-dev/living-ui-marketplace) 瀏覽社群打造的 Agent App。

<div align="center">
    <img src="assets/living-ui-marketplace.png" alt="Agent App marketplace" width="448"/>
</div>

3. **匯入既有專案.** 把 Go、Node.js、Python、Rust,
   或是靜態原始碼或 GitHub 儲存庫交給 CraftBot,它會自動偵測執行環境、設定健康檢查,並包裝成一個 Agent App。

<div align="center">
    <img src="assets/agent-app-import.png" alt="Importing an existing project as a Agent App" width="448"/>
</div>

### 讓 CraftBot 始終參與其中,持續演進

Agent App 永遠沒有「完成」這回事。需求一變,
就讓 Agent 為它加上新功能、重新設計頁面或接上新的資料源。

CraftBot 嵌入在每一個 Agent App 中,並且**對其狀態保持感知**:
它可以讀取目前的 DOM 與表單值、透過 REST API 查詢應用資料,
並代你觸發操作。

### 讓 SaaS 工具保持開放且不停演進

打造、自訂並不斷演進屬於你自己的 Agent App,降低對那些根本沒為你量身打造的訂閱工具的依賴。

---
 
# 三個 5 分鐘內就能試玩的 Agent App
 
- **📋 Kanban 看板**:把任務、後續追蹤與待辦集中到一個地方,CraftBot 可以接手操作,替你完成 PM 工作。
- **📊 習慣追蹤器**:培養並追蹤自己的習慣,用類 GitHub 風格的活動日曆像寫程式一樣維護你的習慣。
- **🐦 Luolinglo**:不是 Duolingo,但你可以學新語言、做單字卡片,並和 CraftBot 一起練習。

**[瀏覽 Agent App 市集並貢獻你的作品 →](https://craftos.net/marketplace)**

---

## 🔧 疑難排解與常見問題

### 缺少 Node.js (瀏覽器模式)
如果執行 `python run.py` 時看到 **「npm not found in PATH」**:
1. 從 [nodejs.org](https://nodejs.org/) 下載(選擇 LTS 版本)
2. 安裝完成後重啟終端機
3. 再次執行 `python run.py`

**替代方案:** 改用 CLI 模式(不需 Node.js):
```bash
python run.py --cli
```

### 安裝時相依套件失敗
安裝程式現在會提供更詳細的錯誤訊息與解決方法。若安裝失敗:
- **檢查 Python 版本:** 確認已安裝 Python 3.10 以上(`python --version`)
- **檢查網路連線:** 安裝過程需要下載相依套件
- **清除 pip 快取:** 執行 `pip install --upgrade pip` 之後再試一次

### Playwright 安裝問題
Playwright Chromium 的安裝為選用項目。即使失敗:
- Agent 在其他任務上**仍可正常運作**
- 可以先略過,稍後再用 `playwright install chromium` 安裝
- 只有在使用 WhatsApp Web 整合時才需要

更完整的排解請參考 [INSTALLATION_FIX.md](INSTALLATION_FIX.md)。

---
## 🐳 使用容器執行

儲存庫根目錄包含一份 Docker 設定,內含 Python 3.10、關鍵系統套件(含用於 OCR 的 Tesseract),以及 `environment.yml`/`requirements.txt` 中定義的所有 Python 相依套件,讓 Agent 在隔離環境中也能穩定運作。

以下是使用容器執行 Agent 的步驟。

### 建立映像檔

從儲存庫根目錄執行:

```bash
docker build -t craftbot .
```

### 執行容器

映像檔預設會以 `python -m app.main` 啟動 Agent。如要互動式執行:

```bash
docker run --rm -it craftbot
```

需要傳入環境變數時,可以指定一個 env 檔案(例如以 `.env.example` 為基礎):

```bash
docker run --rm -it --env-file .env craftbot
```

透過 `-v` 掛載需要持久化到容器外的目錄(例如資料或快取資料夾),並依部署需求調整 port 或其他參數。映像檔內建了 OCR(`tesseract`)所需的系統套件以及常見的 HTTP 客戶端,讓 Agent 可以直接在容器中處理檔案和網路 API。

映像檔預設使用 Python 3.10,並打包好 `environment.yml`/`requirements.txt` 中的相依套件,所以 `python -m app.main` 可以直接運作。

---

## 🤝 如何貢獻

歡迎送 PR!工作流程(fork → 從 `dev` 切分支 → 送 PR)詳見 [CONTRIBUTING.md](CONTRIBUTING.md)。所有 PR 都會自動跑 lint + 冒煙測試 CI。

> [!IMPORTANT]
> **CraftBot** 正在積極開發中,每週都有改進。有問題或想更快交流,歡迎加入 [Discord](https://discord.gg/ZN9YHc37HG),或寄信至 thamyikfoong(at)craftos.net。

---

## 🧾 授權

本專案以 [MIT 授權](LICENSE) 開放原始碼。你可以自由地使用、自架以及商業化本專案(進行散布或商業化時,需保留對本專案的署名)。

---

## ⭐ 致謝

由 [CraftOS](https://craftos.net/) 與貢獻者共同開發與維護。  
如果你覺得 **CraftBot** 有用,歡迎給儲存庫一顆 ⭐ 並分享給更多人!

---

## Star 歷史

<a href="https://star-history.dera.page/#CraftOS-dev/CraftBot&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
 </picture>
</a>
