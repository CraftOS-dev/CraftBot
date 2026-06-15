<div align="center">
    <img src="assets/README_banner.png" alt="CraftBot Banner" width="1280"/>
</div>

<div align="center">
    <img src="assets/craftbot_logo_text_small.png" alt="CraftBot" width="400"/>
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
  <a href="README.md">English</a> | <a href="README.ja.md">日本語</a> | <a href="README.cn.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.es.md">Español</a> | <a href="README.pt-BR.md">Português</a> | <a href="README.fr.md">Français</a> | <a href="README.de.md">Deutsch</a>
</p>

## ✨ 주요 기능

자체 SaaS 도구를 만들고 운영할 수 있는 AI 에이전트라는 점 외에도, CraftBot은 에이전트 하네스로서의 핵심 기능을 모두 갖추고 있어 작업, 도구, 메모리, 일상 워크플로 전반에서 범용 AI 에이전트로 사용자와 함께 일할 수 있습니다.

---

## 🧰 시작하기

요구 사항: Python 3.10+ · 브라우저 모드는 Node.js 18+ 필요

```bash
# 1. 저장소 클론
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. 설치, 자동 시작 등록, CraftBot 실행
python craftbot.py install
```

이것이 전부입니다. 터미널은 자동으로 닫히고, CraftBot은 백그라운드에서 실행되며, 브라우저가 자동으로 열립니다. 언제든 다시 브라우저를 열 수 있도록 **데스크톱 바로가기**도 함께 만들어집니다.

**설치 이후 서비스 관리:**

```bash
python craftbot.py start      # CraftBot을 백그라운드에서 실행
python craftbot.py stop       # CraftBot 중지
python craftbot.py restart    # CraftBot 재시작
python craftbot.py status     # 실행 여부와 자동 시작 활성화 여부 확인
python craftbot.py logs       # 최근 로그 출력 확인
python craftbot.py uninstall  # 중지, 자동 시작 해제, 패키지 제거
```

> [!TIP]
> `install` 또는 `start` 이후에는 **CraftBot 데스크톱 바로가기**가 자동으로 생성됩니다. 브라우저를 닫았다면 바로가기를 더블 클릭하여 다시 열면 됩니다.

---

## 🌱 Living UI

**Living UI는 사용자의 필요에 맞춰 함께 진화하는 시스템/앱/대시보드입니다.**

<div align="center">
    <img src="assets/living_ui_banner.gif" alt="CraftBot Banner" width="1280"/>
</div>

- AI 코파일럿이 내장된 칸반 보드가 필요한가요?
- 당신의 워크플로에 딱 맞춘 커스텀 CRM은요?
- CraftBot이 대신 읽고 조작할 수 있는 회사 대시보드는요?

```bash
# 1. 리포지토리 클론
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. conda 환경에 설치
python install.py --conda

# 3. CraftBot 실행
conda run -n craftbot python run.py

# conda가 PATH에 없는 경우 (Windows 전용):
&"$env:USERPROFILE\miniconda3\Scripts\conda.exe" run -n craftbot python run.py
```

> [!NOTE]
> CraftBot을 실행할 때마다 `conda run -n craftbot python run.py`를 사용하세요. 백그라운드 서비스가 없으므로 직접 시작하고 중지해야 합니다.

---

### 옵션 3 — 수동 설치 (pip)

**이것을 선택하세요:** Python 환경을 완전히 직접 관리하고 싶고, 자동 서비스나 백그라운드 프로세스 없이 CraftBot을 관리하고 싶은 경우.

`install.py`(플래그 없음)는 현재 활성화된 Python 환경에 표준 pip 설치를 수행합니다. `run.py`로 CraftBot을 수동으로 시작하고 중지합니다.

```bash
# 1. 리포지토리 클론
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. 활성 Python 환경에 의존성 설치
python install.py

# 3. CraftBot 실행
python run.py
```

첫 실행 시 API 키 설정 과정을 안내해 줍니다.

> [!NOTE]
> Node.js가 설치되어 있지 않다면 설치 프로그램이 단계별로 안내해 줍니다. CLI 모드를 사용하면 브라우저 모드를 완전히 건너뛸 수도 있습니다 — Node.js 불필요: `python run.py --cli`

### 바로 할 수 있는 일
- 에이전트와 자연스럽게 대화
- 복잡한 다단계 작업 요청
- `/help`를 입력해 사용 가능한 명령 확인
- Google, Slack, Notion 등과 연결

### 🖥️ 인터페이스 모드

<div align="center">
    <img src="assets/WCA_README_banner.png" alt="CraftOS Banner" width="1280"/>
</div>

CraftBot은 여러 UI 모드를 지원합니다. 선호에 따라 선택하세요.

| 모드 | 명령어 | 요구 사항 | 적합한 용도 |
|------|---------|--------------|----------|
| **Browser** | `python run.py` | Node.js 18+ | 최신 웹 인터페이스, 가장 사용하기 쉬움 |
| **CLI** | `python run.py --cli` | 없음 | 커맨드라인, 경량 |

**브라우저 모드**가 기본이자 권장 모드입니다. Node.js가 없는 경우 설치 프로그램이 설치 안내를 제공하거나, 대신 **CLI 모드**를 사용할 수 있습니다.

---

## 🧬 Living UI

**Living UI는 당신의 필요에 따라 진화하는 시스템/앱/대시보드입니다.**

AI 코파일럿이 내장된 칸반 보드가 필요한가요? 당신의 워크플로에 딱 맞게 만든 맞춤형 CRM은요?
CraftBot이 읽고 조작할 수 있는 회사 대시보드는요?
Living UI로 실행하세요 — CraftBot과 함께 작동하며, 당신의 필요가 변할수록 함께 성장합니다.

<div align="center">
    <img src="assets/living-ui-example.png" alt="Living UI example" width="1280"/>
</div>

### Living UI를 만드는 세 가지 방법

1. **처음부터 빌드.** 자연어로 원하는 것을 설명하세요. CraftBot이 데이터 모델, 백엔드 API, React UI를 골조로 잡고, 구조화된 설계 프로세스를 통해 함께 다듬어 갑니다.

<div align="center">
    <img src="assets/living-ui-custom-build.png" alt="Building a Living UI from scratch" width="448"/>
</div>

2. **마켓플레이스에서 설치.** [living-ui-marketplace](https://github.com/CraftOS-dev/living-ui-marketplace)에서 커뮤니티가 만든 Living UI를 둘러보세요.

<div align="center">
    <img src="assets/living-ui-marketplace.png" alt="Living UI marketplace" width="448"/>
</div>

3. **기존 프로젝트 가져오기.** Go, Node.js, Python, Rust 소스 코드나 정적 사이트, GitHub 저장소를 CraftBot에 알려주세요. 런타임을 감지하고 헬스 체크를 설정한 뒤 Living UI로 감싸줍니다.

<div align="center">
    <img src="assets/living-ui-import.png" alt="Importing an existing project as a Living UI" width="448"/>
</div>

### 에이전트를 항상 곁에 두고 계속 진화

Living UI는 "완성"이라는 게 없습니다. 필요가 바뀌면 에이전트에게 기능을 추가하거나, 화면을 다시 디자인하거나, 새로운 데이터를 연결하도록 요청하세요.

CraftBot은 모든 Living UI에 내장되어 있으며 그 **상태를 항상 인지**합니다. 현재 DOM과 폼 값을 읽고, REST API로 앱 데이터를 조회하며, 사용자를 대신해 액션을 트리거할 수 있습니다.

### SaaS 도구를 열린 상태로, 살아 있는 채로

자기 자신만의 Living UI를 만들고, 커스터마이즈하고, 진화시키며, 결코 당신의 필요에 완벽히 맞춰지지 않은 구독형 도구에 대한 의존을 줄여보세요.

우리는 자신만의 Living UI를 선보일 개발자를 적극적으로 찾고 있으며, **[Living UI 마켓플레이스](https://craftos.net/marketplace)**로 내보낼 수 있도록 지원합니다. PR 환영합니다!

---
 
# 5분 안에 체험해 볼 수 있는 Living UI 3종
 
- **📋 칸반 보드** — 모든 작업, 후속 조치, CTA를 한 곳에. CraftBot이 직접 운영하며 PM 업무를 대신 처리할 수 있습니다.
- **📊 습관 트래커** — 습관을 만들고 추적하세요. GitHub 스타일의 활동 캘린더로 개발자처럼 습관을 관리할 수 있습니다.
- **🐦 Luolinglo** — 듀오링고는 아니지만, 새로운 언어를 배우고 플래시카드를 만들며 CraftBot과 함께 연습할 수 있습니다.

## 🧩 아키텍처 개요

| 구성 요소 | 설명 |
|-----------|-------------|
| **Agent Base** | 작업 라이프사이클을 관리하고 구성 요소 간 조정을 담당하며 주요 에이전틱 루프를 처리하는 핵심 오케스트레이션 계층. |
| **LLM Interface** | 여러 LLM 제공자(OpenAI, Gemini, Anthropic, BytePlus, Ollama)를 지원하는 통합 인터페이스. |
| **Context Engine** | KV 캐시를 지원하는 최적화된 프롬프트를 생성합니다. |
| **Action Manager** | 라이브러리에서 액션을 가져와 실행합니다. 커스텀 액션을 쉽게 확장할 수 있습니다. |
| **Action Router** | 작업 요구 사항에 가장 잘 맞는 액션을 지능적으로 선택하고, 필요 시 LLM을 통해 입력 매개변수를 해결합니다. |
| **Event Stream** | 작업 진행 추적, UI 업데이트, 실행 모니터링을 위한 실시간 이벤트 게시 시스템. |
| **Memory Manager** | ChromaDB 기반의 RAG 시맨틱 메모리. 메모리 청킹, 임베딩, 검색, 점진적 업데이트를 처리합니다. |
| **State Manager** | 에이전트 실행 컨텍스트, 대화 이력, 런타임 구성을 추적하는 전역 상태 관리. |
| **Task Manager** | 작업 정의를 관리하며 단순/복잡 작업 모드, 할 일 생성, 다단계 워크플로우 추적을 가능하게 합니다. |
| **Skill Manager** | 플러그형 스킬을 로드하여 에이전트 컨텍스트에 주입합니다. |
| **MCP Adapter** | MCP 도구를 네이티브 액션으로 변환하는 Model Context Protocol 통합. |

---
 
# CraftBot vs. 대안들
 
|                                  | v0 / Lovable / Bolt | OpenClaw | Claude Code | **CraftBot**                            |
| -------------------------------- | ------------------- | -------------------- | -------------------- | --------------------------------------- |
| **커스텀 앱 빌드**           | ✅ 일회성         | 🚫                   | ✅ (수동)          | ✅ 대화형                       |
| **에이전트가 앱을 직접 조작**       | 🚫                  | ⚠️ 도구 호출 방식      | 🚫                   | ✅ 모든 Living UI에 내장         |
| **영속적인 에이전트 메모리**      | 🚫                  | ✅            | ✅                   | ✅ RAG + 에이전트 파일 시스템 + 디스틸레이션        |
| **셀프 호스트**     | ⚠️ 부분 지원         | ✅                   | 🚫 SaaS              | ✅ MIT, 내 컴퓨터에서                    |
| **모델 비의존**     | ✅         | ✅                   | ⚠️ 부분 지원              | ✅ 주요 프로바이더 + OpenRouter                    |
 
---

## 🔧 트러블슈팅과 자주 묻는 문제

### install.py

| 플래그 | 설명 |
|------|-------------|
| `--conda` | conda 환경 사용 (선택 사항) |

### run.py

| 플래그 | 설명 |
|------|-------------|
| (없음) | **Browser** 모드로 실행 (권장, Node.js 필요) |
| `--cli` | **CLI** 모드로 실행 (경량) |

### craftbot.py

| 명령 | 설명 |
|---------|-------------|
| `install` | 의존성 설치, 자동 시작 등록, CraftBot 실행 |
| `start` | CraftBot을 백그라운드에서 실행 |
| `stop` | CraftBot 중지 |
| `restart` | 중지 후 다시 시작 |
| `status` | 실행 상태 및 자동 시작 상태 표시 |
| `logs [-n N]` | 마지막 N개의 로그 라인 표시 (기본값: 50) |
| `uninstall` | 자동 시작 등록 해제 |

**설치 예시:**
```bash
# 간단한 pip 설치 (conda 미사용)
python install.py

# conda 환경 사용 (conda 사용자에게 권장)
python install.py --conda
```

**CraftBot 실행:**

```powershell
# Browser 모드 (기본, Node.js 필요)
python run.py

# CLI 모드 (경량)
python run.py --cli

# conda 환경에서 실행
conda run -n craftbot python run.py

# conda가 PATH에 없는 경우 전체 경로 사용
&"$env:USERPROFILE\miniconda3\Scripts\conda.exe" run -n craftbot python run.py
```

**Linux/macOS (Bash):**
```bash
# Browser 모드 (기본, Node.js 필요)
python run.py

# CLI 모드 (경량)
python run.py --cli

# conda 환경에서 실행
conda run -n craftbot python run.py
```

### 🔧 백그라운드 서비스 (권장)

터미널을 닫아도 CraftBot이 계속 실행되도록 백그라운드 서비스로 실행합니다. 데스크톱 바로가기가 자동으로 생성되므로 언제든지 브라우저를 다시 열 수 있습니다.

```bash
# 의존성 설치, 로그인 시 자동 시작 등록, CraftBot 실행
python craftbot.py install
```

이게 전부입니다. 터미널은 자동으로 닫히고, CraftBot은 백그라운드에서 실행되며, 브라우저가 자동으로 열립니다.

```bash
# 기타 서비스 명령:
python craftbot.py start    # CraftBot을 백그라운드에서 시작
python craftbot.py status   # 실행 여부 확인
python craftbot.py stop     # CraftBot 중지
python craftbot.py restart  # CraftBot 재시작
python craftbot.py logs     # 최근 로그 출력 확인
```

| 명령 | 설명 |
|---------|-------------|
| `python craftbot.py install` | 의존성 설치, 로그인 시 자동 시작 등록, CraftBot 실행, 브라우저 열기 후 터미널 자동 종료 |
| `python craftbot.py start` | CraftBot을 백그라운드에서 시작 — 이미 실행 중이면 자동 재시작 (터미널 자동 종료) |
| `python craftbot.py stop` | CraftBot 중지 |
| `python craftbot.py restart` | CraftBot 중지 후 재시작 |
| `python craftbot.py status` | CraftBot 실행 여부와 자동 시작 활성화 여부 확인 |
| `python craftbot.py logs` | 최근 로그 출력 표시 (`-n 100`으로 더 많은 줄 표시) |
| `python craftbot.py uninstall` | CraftBot 중지, 자동 시작 등록 해제, pip 패키지 제거 및 pip 캐시 정리 |

> [!TIP]
> `craftbot.py start` 또는 `craftbot.py install` 실행 후 **CraftBot 데스크톱 바로가기**가 자동으로 생성됩니다. 브라우저를 실수로 닫았다면 바로가기를 더블클릭해 다시 열 수 있습니다.

> [!NOTE]
> **설치:** 의존성이 누락된 경우 설치 프로그램이 명확한 안내를 제공합니다. Node.js가 없으면 설치 여부를 묻거나 CLI 모드로 전환할 수 있습니다. GPU 가용성을 자동으로 감지하고 필요한 경우 CPU 전용 모드로 대체합니다.

> [!TIP]
> **첫 실행 설정:** CraftBot은 API 키, 에이전트 이름, MCP, 스킬 설정을 위한 온보딩 과정을 안내합니다.

> [!NOTE]
> **Playwright Chromium:** WhatsApp Web 통합에 필요한 선택 사항입니다. 설치에 실패해도 다른 작업에서는 에이전트가 정상 작동합니다. 나중에 `playwright install chromium`으로 수동 설치할 수 있습니다.

---

## 🔧 문제 해결 및 자주 발생하는 이슈

### Node.js 누락 (브라우저 모드용)
`python run.py` 실행 시 **"npm not found in PATH"** 오류가 보인다면:
1. [nodejs.org](https://nodejs.org/)에서 다운로드 (LTS 버전 권장)
2. 설치 후 터미널 재시작
3. 다시 `python run.py` 실행

**대안:** CLI 모드를 사용하세요 (Node.js 불필요):
```bash
python run.py --cli
```

### 의존성 때문에 설치가 실패할 때
설치 프로그램이 이제 상세한 에러 메시지와 해결 방법을 제공합니다. 설치가 실패한다면:
- **Python 버전 확인:** Python 3.10 이상인지 확인 (`python --version`)
- **인터넷 연결 확인:** 설치 중에 의존성을 다운로드합니다
- **pip 캐시 정리:** `pip install --upgrade pip` 실행 후 다시 시도

### Playwright 설치 문제
Playwright Chromium 설치는 선택 사항입니다. 실패하더라도:
- 다른 작업에서는 에이전트가 **정상적으로 동작**합니다
- 일단 건너뛰고 나중에 `playwright install chromium`으로 설치할 수 있습니다
- WhatsApp Web 연동을 사용할 때만 필요합니다

자세한 트러블슈팅은 [INSTALLATION_FIX.md](INSTALLATION_FIX.md)를 참고하세요.

---
## 🐳 컨테이너로 실행

저장소 루트에는 Python 3.10, 주요 시스템 패키지(OCR을 위한 Tesseract 포함), 그리고 `environment.yml`/`requirements.txt`에 정의된 모든 Python 의존성을 포함하는 Docker 구성이 들어 있어, 격리된 환경에서도 에이전트를 일관되게 실행할 수 있습니다.

다음은 컨테이너로 에이전트를 실행하는 방법입니다.

### 이미지 빌드

저장소 루트에서 실행:

```bash
docker build -t craftbot .
```

### 컨테이너 실행

이미지는 기본적으로 `python -m app.main`으로 에이전트를 실행하도록 설정되어 있습니다. 인터랙티브하게 실행하려면:

```bash
docker run --rm -it craftbot
```

환경 변수를 전달해야 한다면 env 파일을 전달하세요 (예: `.env.example`을 기반으로 작성):

```bash
docker run --rm -it --env-file .env craftbot
```

컨테이너 바깥에 유지되어야 할 디렉터리(데이터, 캐시 등)는 `-v`로 마운트하고, 포트나 추가 플래그는 배포 환경에 맞춰 조정하세요. 이미지에는 OCR(`tesseract`)에 필요한 시스템 의존성과 흔히 쓰이는 HTTP 클라이언트가 포함되어 있어, 에이전트가 컨테이너 안에서도 파일과 네트워크 API를 다룰 수 있습니다.

이미지는 기본적으로 Python 3.10을 사용하며 `environment.yml`/`requirements.txt`의 Python 의존성을 함께 패키징해 두었기 때문에, `python -m app.main`이 곧바로 동작합니다.

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

<a href="https://www.star-history.com/?repos=CraftOS-dev%2FCraftBot&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
 </picture>
</a>
