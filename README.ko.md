<div align="center">
    <img src="assets/README_cover.png" alt="CraftBot" width="1280"/>
</div>

대부분의 에이전트 하네스는 채팅과 도구 호출에서 멈춥니다. CraftBot은 거기서 한 발 더 나아갑니다. 자신만의 SaaS 도구를 직접 만들고, 진화시키고, 운영하며, 그 도구 계층을 통해 사용자와 소통하고 자동화를 수행합니다.

그 외에도 CraftBot은 범용 에이전트 하네스의 핵심 기능을 모두 갖추고 있습니다. 원격 직원처럼 작업을 수행하고, 사용자의 선호와 목표를 기억하며, 사용자에게 중요한 일을 주도적으로 계획하고 실행하도록 돕습니다.

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
  <a href="README.md">English</a> | <a href="README.ja.md">日本語</a> | <a href="README.cn.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.es.md">Español</a> | <a href="README.pt-BR.md">Português</a> | <a href="README.fr.md">Français</a> | <a href="README.de.md">Deutsch</a>
</p>

## ✨ 주요 기능

자체 SaaS 도구를 만들고 운영할 수 있는 AI 에이전트라는 점 외에도, CraftBot은 에이전트 하네스로서의 핵심 기능을 모두 갖추고 있어 작업, 도구, 메모리, 일상 워크플로 전반에서 범용 AI 에이전트로 사용자와 함께 일할 수 있습니다.

- **에이전트 프로필** 40개 이상의 에이전트 프로필(CEO 에이전트, 재무 에이전트, 마케팅 리드 에이전트, DevOps 엔지니어, 영상 프로듀서 에이전트 등 37종)이 당신을 위해 일할 준비가 되어 있습니다. **[CraftBot Agent Bundles](https://github.com/CraftOS-dev/craftbot-agent-bundles)** 에서 원하는 역할을 찾아 원클릭으로 가져올 수 있습니다.
- **플레이북 카탈로그** AI 에이전트로 무엇을 자동화해야 할지 모르시겠나요? CraftBot에는 120개의 플레이북(19개 카테고리에 걸쳐)이 바로 사용할 수 있도록 준비되어 있습니다. 상단 바에서 플레이북 선택기를 열고 플레이북을 고르면, 바로 작업을 실행해 줍니다.
- **Agent App.** CraftBot 안에서 동작하는 커스텀 앱을 만들고, 가져오고, 발전시킬 수 있습니다. 에이전트는 UI의 상태를 항상 인지하고 있으며, 그 데이터를 직접 읽고 쓰고 다룰 수 있습니다.
- **멀티태스킹과 세션 라우팅.** 아직도 `/new` 명령어를 직접 입력하시나요? CraftBot은 언제 새 세션을 시작하고 언제 기존 작업을 이어갈지 스스로 판단하여 대화와 컨텍스트를 하나로 유지합니다.
- **셀프 호스팅 & BYOK.** OpenAI, Google Gemini, Anthropic Claude, OpenRouter 등을 지원하는 유연한 LLM 제공자 시스템. 또는 Ollama로 토큰 소비 0으로 자신만의 모델을 호스팅할 수 있습니다.
- **메모리 시스템.** CraftBot과의 상호작용으로부터 구축되는 세컨드 브레인입니다. 하이브리드 방식: RAG + 지식 그래프 + 에이전트 파일 시스템. CraftBot은 자정에 "꿈을 꾸며" 하루 동안 일어난 이벤트를 통합합니다.
- **능동적 에이전트.** 당신의 선호, 습관, 인생 목표를 학습합니다. 그리고 계획을 세우고 작업을 시작(물론 승인을 받아)하여 당신이 인생에서 더 나아질 수 있도록 돕습니다.
- **외부 도구 통합.** Google Workspace, Slack, Notion, Zoom, LinkedIn, Discord, Telegram 등 당신의 앱(더 많이 추가될 예정!)과 OAuth 또는 자체 키로 연결할 수 있습니다. 각 통합에 여러 계정을 연결할 수 있습니다.
- **Skills와 MCP.** 150개 이상의 MCP와 170개 이상의 Skills가 준비되어 있습니다. 새로운 Skills와 MCP를 빠르게 설치할 수 있고, 완료된 작업에서 한 번의 클릭으로 Skills를 만들거나 개선할 수 있습니다.
- **브라우저 인터페이스와 CLI 지원.** 당신에게 맞는 방식으로 CraftBot을 사용하세요. 일상적인 사용에는 간단한 브라우저 UI를, 스크립팅과 헤드리스 환경에는 CLI를 사용할 수 있습니다.

---


## 🧰 시작하기

**요구 사항**

- Windows 10 또는 11(x64), macOS 12 이상(Apple Silicon 또는 Intel), 또는 Linux(x86_64 또는 ARM64)
- 5 GB 이상의 여유 디스크 공간
- LLM 제공업체(OpenAI, Anthropic, Google Gemini, OpenRouter 등)의 API 키, 또는 Ollama로 실행하는 로컬 모델
- 소스 설치에만 필요: Python 3.8 이상. Node.js는 필요하지 않습니다.

### 방법 1: 설치 프로그램(권장, Python과 Git 불필요)

[최신 릴리스](https://github.com/CraftOS-dev/CraftBot/releases/latest)에서 사용 중인 시스템에 맞는 파일을 내려받으세요.

| 시스템 | 파일 |
|---|---|
| Windows(x64) | `CraftBotInstaller-windows.exe` |
| macOS(Apple Silicon 및 Intel) | `CraftBotInstaller-macos.zip` |
| Linux(x86_64) | `CraftBotInstaller-linux-x86_64` |
| Linux(ARM64) | `CraftBotInstaller-linux-aarch64` |

파일을 열고 **Install CraftBot**을 클릭합니다. 설치 프로그램이 CraftBot에 필요한 모든 것을 내려받고, CraftBot을 시작한 뒤 브라우저에서 엽니다.

설치 프로그램은 아직 코드 서명이 되어 있지 않아 처음 실행할 때 한 단계가 더 필요합니다.

- **Windows:** SmartScreen에 "Windows의 PC 보호" 메시지가 표시되면 **추가 정보**(More info)를 클릭한 다음 **실행**(Run anyway)을 클릭합니다.
- **macOS:** 파일의 압축을 풀고 `CraftBotInstaller.app`을 엽니다. macOS 15 이상에서는 처음 실행이 차단됩니다. **시스템 설정 > 개인정보 보호 및 보안**을 열고 CraftBotInstaller 관련 메시지 옆의 **그래도 열기**(Open Anyway)를 클릭한 뒤 확인합니다. macOS 12부터 14까지는 앱을 마우스 오른쪽 버튼으로 클릭하고 **열기**(Open)를 선택합니다.
- **Linux:** 파일에 실행 권한을 주고 데스크톱 세션에서 실행합니다(데스크톱이 없는 서버에서는 소스 설치를 사용하세요).
  ```bash
  chmod +x CraftBotInstaller-linux-x86_64
  ./CraftBotInstaller-linux-x86_64
  ```

### 방법 2: 소스에서 설치

컴퓨터에 이미 있는 Python 3.8 이상이면 어떤 버전이든 됩니다. CraftBot은 전용 Python 3.10과 Node.js 24를 직접 내려받으며, 시스템에 설치된 Python이나 Node.js는 변경하지 않습니다.

```bash
git clone --depth 1 https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot
```

그다음 사용 중인 시스템에 맞는 설치 명령을 실행합니다.

```bash
# Windows
python craftbot.py install        # 또는: py craftbot.py install

# macOS 및 Linux
python3 craftbot.py install
```

- **Git이 없나요?** [저장소 페이지](https://github.com/CraftOS-dev/CraftBot)에서 **Code > Download ZIP**을 클릭하고, 압축을 푼 폴더에서 터미널을 열어 같은 명령을 실행하세요.
- **Python이 없거나 3.8보다 오래된 버전인가요?** 설치 프로그램(방법 1)을 사용하세요.

첫 설치에서는 약 1 GB를 내려받으며, 일반적인 네트워크에서 몇 분 정도 걸립니다. 완료되면 CraftBot이 백그라운드에서 실행되고, 브라우저에서 http://localhost:7925를 열며, 데스크톱 바로가기를 만듭니다. 7925 또는 7926 포트가 이미 사용 중이면 CraftBot은 다음 빈 포트를 사용하고 열어야 할 주소를 출력합니다.

처음 시작할 때 브라우저 온보딩에서 LLM API 키를 입력합니다. CraftBot은 키를 `app/config/settings.json`에 저장하며(나중에 설정에서 변경 가능), `.env` 파일에서 API 키를 읽지 않습니다.

### CraftBot 관리

설치할 때와 같은 `python` 또는 `python3` 명령을 사용합니다.

```bash
python craftbot.py start      # 백그라운드에서 CraftBot 시작
python craftbot.py stop       # CraftBot 중지
python craftbot.py restart    # CraftBot 재시작
python craftbot.py status     # 실행 여부와 자동 시작 등록 여부 확인
python craftbot.py logs       # 최근 50줄의 로그 표시(더 보려면 logs -n 200)
python craftbot.py uninstall  # 중지, 자동 시작 해제, 패키지 제거
python run.py --cli           # 브라우저 대신 터미널에서 실행
```

설치 프로그램을 사용하는 경우 설치 프로그램 창에서 같은 작업을 할 수 있습니다(**Start**, **Stop**, **Repair**, **Uninstall**).

> [!TIP]
> `install` 또는 `start` 이후에는 **CraftBot 데스크톱 바로가기**가 자동으로 생성됩니다. 브라우저를 닫았다면 바로가기를 더블 클릭하여 다시 열 수 있습니다.

---

## 🌱 Agent App

**Agent App는 사용자의 필요에 맞춰 함께 진화하는 시스템/앱/대시보드입니다.**

<div align="center">
    <img src="assets/agent_app_banner.gif" alt="CraftBot Banner" width="1280"/>
</div>

- AI 코파일럿이 내장된 칸반 보드가 필요한가요?
- 당신의 워크플로에 딱 맞춘 커스텀 CRM은요?
- CraftBot이 대신 읽고 조작할 수 있는 회사 대시보드는요?

CraftBot과 나란히 실행되고, 필요가 변할수록 함께 성장하는 Agent App로 띄워 보세요.

### Agent App를 만드는 세 가지 방법

1. **처음부터 빌드.** 자연어로 원하는 것을 설명하세요. CraftBot이
   데이터 모델, 백엔드 API, React UI를 골조로 잡고, 구조화된
   설계 프로세스를 통해 함께 다듬어 갑니다.

<div align="center">
    <img src="assets/agent-app-custom-build.png" alt="Building a Agent App from scratch" width="448"/>
</div>

2. **마켓플레이스에서 설치.** [living-ui-marketplace](https://github.com/CraftOS-dev/living-ui-marketplace)에서 커뮤니티가 만든 Agent App를 둘러보세요.

<div align="center">
    <img src="assets/living-ui-marketplace.png" alt="Agent App marketplace" width="448"/>
</div>

3. **기존 프로젝트 가져오기.** Go, Node.js, Python, Rust 소스 코드나
   정적 사이트, GitHub 저장소를 CraftBot에 알려주세요. 런타임을 감지하고 헬스 체크를 설정한 뒤 Agent App로 감싸줍니다.

<div align="center">
    <img src="assets/agent-app-import.png" alt="Importing an existing project as a Agent App" width="448"/>
</div>

### CraftBot을 루프 안에 두고 계속 진화

Agent App는 "완성"이라는 게 없습니다. 필요가 바뀌면 에이전트에게 기능을
추가하거나, 화면을 다시 디자인하거나, 새로운 데이터를 연결하도록 요청하세요.

CraftBot은 모든 Agent App에 내장되어 있으며 그 **상태를 항상 인지**합니다.
현재 DOM과 폼 값을 읽고, REST API로 앱 데이터를 조회하며,
사용자를 대신해 액션을 트리거할 수 있습니다.

### SaaS 도구를 열린 상태로, 살아 있는 채로

자기 자신만의 Agent App를 만들고, 커스터마이즈하고, 진화시키며, 결코 당신의 필요에 완벽히 맞춰지지 않은 구독형 도구에 대한 의존을 줄여보세요.

---
 
# 5분 안에 체험해 볼 수 있는 Agent App 3종
 
- **📋 칸반 보드**: 모든 작업, 후속 조치, CTA를 한 곳에. CraftBot이 직접 운영하며 PM 업무를 대신 처리할 수 있습니다.
- **📊 습관 트래커**: 습관을 만들고 추적하세요. GitHub 스타일의 활동 캘린더로 개발자처럼 습관을 관리할 수 있습니다.
- **🐦 Luolinglo**: 듀오링고는 아니지만, 새로운 언어를 배우고 플래시카드를 만들며 CraftBot과 함께 연습할 수 있습니다.

**[Agent App 마켓플레이스 둘러보고 기여하기 →](https://craftos.net/marketplace)**

---

## 🔧 문제 해결 및 자주 발생하는 이슈

**먼저 로그를 확인하세요.** `python craftbot.py logs`는 최근 50줄을 보여 줍니다(더 보려면 `logs -n 200`). `install` 또는 `start`가 실패하면 로그의 마지막 부분을 출력하고 오류로 종료합니다. `python craftbot.py doctor`는 아무것도 변경하지 않고 각 설치 단계를 점검합니다. 설치 프로그램에서는 **Open log**를 클릭합니다.

**설치는 다시 실행해도 안전합니다.** `python craftbot.py install`은 이미 성공한 단계를 건너뛰고 나머지만 다시 시도합니다. 설치 프로그램에서는 **Repair**를 클릭합니다.

### 7925 또는 7926 포트가 이미 사용 중일 때

CraftBot은 다음 빈 포트로 옮기고 열어야 할 주소를 출력합니다. 포트를 직접 지정하려면 다음과 같이 실행합니다.

```bash
python craftbot.py start --frontend-port 8925 --backend-port 8926
```

### 프록시 또는 회사 네트워크

모든 다운로드(Python, pip, npm, Node.js)는 표준 프록시 환경 변수를 사용합니다. 설치하기 전에 같은 터미널에서 설정하세요.

```bash
# macOS 및 Linux
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

TLS 트래픽을 검사하는 네트워크에서도 추가 설정이 필요 없습니다. CraftBot은 운영 체제 인증서 저장소의 인증서를 신뢰합니다.

### 다운로드가 느리거나 막힐 때(예: 중국 본토)

설치하기 전에 다운로드 주소를 미러로 지정하세요.

| 변수 | 용도 | 예시 |
|---|---|---|
| `PIP_INDEX_URL` | Python 패키지 | `https://pypi.tuna.tsinghua.edu.cn/simple` |
| `npm_config_registry` | npm 패키지 | `https://registry.npmmirror.com` |
| `HF_ENDPOINT` | 임베딩 모델 | `https://hf-mirror.com` |
| `CRAFTBOT_MIRRORS` | Python, Node.js, PocketBase, 임베딩 모델 다운로드 | 아래 참고 |

`CRAFTBOT_MIRRORS`는 `prefix=replacement`(접두사=대체 주소) 형식의 URL 재작성 규칙을 세미콜론으로 구분한 목록입니다.

```bash
export CRAFTBOT_MIRRORS="https://github.com/=https://<your-github-proxy>/https://github.com/;https://nodejs.org/dist/=https://npmmirror.com/mirrors/node/"
```

Python 패키지와 메모리 임베딩 모델은 미러를 거쳐도 고정된 SHA-256 체크섬으로 검증되므로, 미러가 이를 바꿀 수 없습니다. Python과 Node.js 런타임은 체크섬이 고정되어 있지 않으므로, 신뢰할 수 있는 미러만 사용하세요. Windows PowerShell에서는 `export` 대신 `$env:NAME = "value"`로 변수를 설정합니다.

### 데스크톱이 없는 서버

서버에서 브라우저를 열지 않고 소스로 설치합니다.

```bash
python3 craftbot.py install --no-open-browser
```

CraftBot은 `localhost`에서만 수신하며, `localhost`로 접속한 브라우저 연결만 받습니다. 내 컴퓨터에서 사용하려면 두 포트를 같은 번호로 전달하는 SSH 터널을 연 다음, 내 컴퓨터에서 http://localhost:7925를 엽니다.

```bash
ssh -L 7925:localhost:7925 -L 7926:localhost:7926 user@server
```

`CRAFTBOT_BIND_HOST`를 설정하면 CraftBot이 다른 네트워크 인터페이스에서 수신합니다(Docker 이미지는 `0.0.0.0` 사용). 원격 접속에는 여전히 SSH 터널을 사용하세요.

### Linux: 재부팅 후 CraftBot이 시작되지 않을 때

자동 시작은 systemd 사용자 서비스이므로 systemd 사용자 세션이 필요합니다. 로그인하지 않아도 부팅 시 CraftBot이 시작되고 로그아웃 후에도 계속 실행되게 하려면 다음 명령을 한 번 실행합니다.

```bash
loginctl enable-linger $USER
```

systemd가 없는 환경(예: systemd를 켜지 않은 WSL)에서는 부팅할 때마다 `python3 craftbot.py start`를 실행하세요.

### macOS: 설치 프로그램이 차단될 때

설치 프로그램은 아직 코드 서명이 되어 있지 않습니다. macOS 15 이상에서는 한 번 열기를 시도한 뒤 **시스템 설정 > 개인정보 보호 및 보안**을 열고 **그래도 열기**(Open Anyway)를 클릭합니다. macOS 12부터 14까지는 앱을 마우스 오른쪽 버튼으로 클릭하고 **열기**(Open)를 선택합니다.

### Windows: SmartScreen이 설치 프로그램을 차단할 때

**추가 정보**(More info)를 클릭한 다음 **실행**(Run anyway)을 클릭합니다. 이 경고는 설치 프로그램이 아직 코드 서명되지 않았기 때문에 표시됩니다.

### Windows: `python`을 입력하면 Microsoft Store가 열릴 때

Python이 설치되어 있지 않다는 뜻입니다. 설치 프로그램을 사용하거나, [python.org](https://www.python.org/downloads/)에서 Python을 설치한 뒤 `py craftbot.py install`을 실행하세요.

### CraftBot 데이터를 다른 위치에 두기

설치하기 전에 `CRAFTBOT_HOME`을 폴더로 지정하면 CraftBot의 모든 데이터와 내려받은 런타임이 그 폴더(예: 용량이 큰 드라이브)에 저장됩니다. 자동 시작도 이 설정을 유지합니다.

### 브라우저 기능(Playwright)

Mini Browser와 브라우저 자동화는 Playwright의 Chromium을 사용합니다. 이 다운로드가 실패해도 CraftBot의 나머지 기능은 정상적으로 동작합니다. 나중에 `python craftbot.py install`을 다시 실행하면 재시도합니다.

---

## 🐳 컨테이너로 실행

Docker 이미지는 필요한 모든 것이 미리 설치된 상태로 CraftBot을 브라우저 모드로 실행합니다. Python 3.10과 고정된 의존성, Node.js 24, 브라우저 UI, PocketBase, Playwright의 Chromium이 포함되어 있습니다.

저장소 루트에서 다음을 실행합니다.

```bash
docker compose up -d
```

첫 빌드에는 몇 분이 걸립니다. 그다음 http://localhost:7925를 열고 온보딩에서 LLM API 키를 입력합니다.

설정과 API 키, 에이전트 파일, 메모리, 로그는 `craftbot-data` 볼륨에 저장되므로 컨테이너를 다시 시작하거나 이미지를 다시 빌드해도 유지됩니다.

```bash
docker compose logs -f craftbot              # 로그 실시간 보기
docker compose ps                            # 헬스 체크를 포함한 상태 확인
docker compose down                          # 중지(데이터 볼륨은 유지됨)
git pull && docker compose up -d --build     # 최신 버전으로 업데이트
```

- CraftBot UI에는 자체 로그인 기능이 없으므로 포트는 `127.0.0.1`에만 공개됩니다. 원격 서버에서도 이 설정을 유지하고, 문제 해결 섹션에서 설명한 SSH 터널로 접속하세요. 호스트 포트는 7925와 7926으로 유지하세요. CraftBot은 이 포트로 `localhost`를 통해 접속한 브라우저 연결만 받습니다.
- 셸 또는 `docker-compose.yml`과 같은 폴더의 `.env` 파일에 설정한 프록시 및 미러 변수(`HTTPS_PROXY`, `PIP_INDEX_URL`, `HF_ENDPOINT`, `CRAFTBOT_MIRRORS`, 그리고 `.env.example`에 나열된 기타 변수)는 컨테이너로 전달됩니다.
- Agent App은 컨테이너 안의 3100~3199 포트에서 실행되며, 아직 호스트 브라우저에서 열 수 없습니다. Agent App을 사용하려면 설치 프로그램이나 소스 설치를 사용하세요.
- Compose 없이 실행하려면:
  ```bash
  docker build -t craftbot .
  docker run -d --name craftbot -p 127.0.0.1:7925:7925 -p 127.0.0.1:7926:7926 --shm-size 1g -v craftbot-data:/data craftbot
  ```

---

## 🤝 기여 방법

PR 환영합니다! 워크플로(fork → `dev`에서 브랜치 → PR)는 [CONTRIBUTING.md](CONTRIBUTING.md)를 참고하세요. 모든 PR은 자동으로 lint + 스모크 테스트 CI를 통과해야 합니다. 

> [!IMPORTANT]
> **CraftBot**은 매주 개선이 이루어지는, 활발히 개발 중인 프로젝트입니다. 질문이 있거나 더 빠른 대화를 원한다면 [Discord](https://discord.gg/ZN9YHc37HG)에 참여하시거나, thamyikfoong(at)craftos.net 로 이메일을 보내주세요.

---

## 🧾 라이선스

이 프로젝트는 [MIT 라이선스](LICENSE) 하에 배포됩니다. 자유롭게 사용, 호스팅, 수익화할 수 있습니다 (배포 및 수익화 시에는 본 프로젝트에 대한 출처 표기가 필요합니다).

---

## ⭐ 감사의 말

[CraftOS](https://craftos.net/)와 기여자들이 함께 개발하고 유지보수합니다.  
**CraftBot**이 도움이 되었다면 저장소에 ⭐를 눌러주시고 주변에 공유해 주세요!

---

## Star 히스토리

<a href="https://star-history.dera.page/#CraftOS-dev/CraftBot&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
 </picture>
</a>
