<div align="center">
    <img src="assets/living_ui_banner.gif" alt="CraftBot Banner" width="1280"/>
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

- **Living UI.** CraftBot 안에서 동작하는 커스텀 앱을 빌드하고, 가져오고, 진화시킬 수 있습니다. 에이전트는 UI의 상태를 항상 인지하며 그 데이터를 직접 읽고, 쓰고, 조작할 수 있습니다.
- **멀티태스킹과 세션 라우팅.** 아직도 `/new` 명령을 직접 입력하고 있나요? CraftBot은 새 세션을 시작해야 할 때와 기존 작업을 이어가야 할 때를 스스로 판단해 대화와 컨텍스트를 하나로 유지합니다.
- **셀프 호스트와 BYOK.** OpenAI, Google Gemini, Anthropic Claude, OpenRouter 등을 지원하는 유연한 LLM 프로바이더 시스템. Ollama로 직접 모델을 호스트해서 토큰을 전혀 쓰지 않을 수도 있습니다.
- **메모리 시스템.** RAG + 에이전트 파일 시스템 + 디스틸레이션을 통해 사용자와 CraftBot의 상호작용에서 로컬 지식 베이스를 구축합니다. CraftBot은 자정에 "꿈을 꾸며" 하루 동안 일어난 사건들을 통합합니다.
- **선제적인 에이전트.** 사용자의 선호, 습관, 인생 목표를 학습한 뒤, 계획을 세우고 (물론 승인을 받아) 작업을 시작해 사용자가 더 나은 삶을 살도록 돕습니다.
- **외부 도구 통합.** 임베디드 자격증명과 OAuth를 지원하며, Google Workspace, Slack, Notion, Zoom, LinkedIn, Discord, Telegram과 연결할 수 있습니다 (더 많은 도구가 추가될 예정입니다!).
- **Skills와 MCP.** 150개 이상의 MCP와 170개 이상의 Skills가 즉시 사용 가능합니다. 새로운 Skills와 MCP를 빠르게 설치할 수 있고, 완료된 작업으로부터 클릭 한 번으로 Skills를 만들거나 개선할 수 있습니다.
- **크로스 플랫폼.** Windows, macOS, Linux를 완벽히 지원하며, 플랫폼별 코드 분기와 Docker 컨테이너화를 제공합니다.
- **브라우저 인터페이스와 CLI 지원.** 사용 환경에 맞춰 선택할 수 있습니다. 일상적인 사용은 가벼운 브라우저 UI로, 스크립팅이나 헤드리스 환경에서는 CLI로 사용하세요.

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

- AI 코파일럿이 내장된 칸반 보드가 필요한가요?
- 당신의 워크플로에 딱 맞춘 커스텀 CRM은요?
- CraftBot이 대신 읽고 조작할 수 있는 회사 대시보드는요?

CraftBot과 나란히 동작하는 Living UI로 띄워두고, 필요에 따라 함께 성장시키세요.

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

**[Living UI 마켓플레이스 둘러보기 및 기여하기 →](https://craftos.net/marketplace)**

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

### Node.js가 없습니다 (브라우저 모드)
`python run.py` 실행 시 **"npm not found in PATH"** 가 표시된다면:
1. [nodejs.org](https://nodejs.org/)에서 LTS 버전 다운로드
2. 설치 후 터미널 재시작
3. 다시 `python run.py` 실행

**대안:** Node.js가 필요 없는 TUI 모드를 사용하세요:
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
