
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
    <img src="https://img.shields.io/badge/Discord-Junte--se%20%C3%A0%20comunidade-5865F2?logo=discord&logoColor=white" alt="Discord">
  </a>
<br/>
<br/>

[![SPONSORED BY E2B FOR STARTUPS](https://img.shields.io/badge/SPONSORED%20BY-E2B%20FOR%20STARTUPS-ff8800?style=for-the-badge)](https://e2b.dev/startups)

<a href="https://www.producthunt.com/products/craftbot?embed=true&amp;utm_source=badge-top-post-badge&amp;utm_medium=badge&amp;utm_campaign=badge-craftbot" target="_blank" rel="noopener noreferrer"><img alt="CraftBot - Self-hosted proactive AI assistant that lives locally | Product Hunt" width="250" height="54" src="https://api.producthunt.com/widgets/embed-image/v1/top-post-badge.svg?post_id=1110300&amp;theme=dark&amp;period=daily&amp;t=1776679679509"></a>
</div>

<p align="center">
  <a href="README.md">English</a> | <a href="README.ja.md">日本語</a> | <a href="README.cn.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ko.md">한국어</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.de.md">Deutsch</a>
</p>

## 🚀 Visão geral
<h3 align="center">
O CraftBot é o seu Assistente de IA Pessoal, que vive dentro da sua máquina e trabalha 24/7 para você.
</h3>

Ele interpreta tarefas de forma autônoma, planeja ações e as executa para alcançar seus objetivos.
Aprende suas preferências e metas, ajudando-o proativamente a planejar e iniciar tarefas para atingir seus objetivos de vida.
Suporta MCPs, Skills e integrações com aplicativos externos.

O CraftBot aguarda suas ordens. Configure o seu agora mesmo.

<div align="center">
    <img src="assets/craftbot_overview.png" alt="CraftBot Overview" width="1280"/>
</div>

---

## ✨ Recursos

- **Bring Your Own Key (BYOK)** — Sistema flexível de provedores de LLM com suporte a OpenAI, Google Gemini, Anthropic Claude, BytePlus e modelos locais do Ollama. Troque de provedor com facilidade.
- **Sistema de Memória** — Destila e consolida os eventos ocorridos durante o dia à meia-noite.
- **Agente Proativo** — Aprende suas preferências, hábitos e metas de vida. Depois, planeja e inicia tarefas (com sua aprovação, claro) para ajudá-lo a evoluir.
- **Living UI** — Construa, importe ou evolua aplicativos personalizados que vivem dentro do CraftBot. O agente permanece ciente do estado da UI e pode ler, escrever e agir sobre seus dados diretamente.
- **Integração com ferramentas externas** — Conecte-se a Google Workspace, Slack, Notion, Zoom, LinkedIn, Discord e Telegram (mais a caminho!) com credenciais embutidas e suporte a OAuth.
- **MCP** — Integração com o Model Context Protocol para ampliar as capacidades do agente com ferramentas e serviços externos.
- **Skills** — Framework de skills extensível com skills embutidas para planejamento de tarefas, pesquisa, revisão de código, operações de git e muito mais.
- **Multiplataforma** — Suporte completo para Windows, macOS e Linux, com variantes de código específicas por plataforma e conteinerização via Docker.

> [!IMPORTANT]
> **O modo GUI foi descontinuado.** O CraftBot não oferece mais suporte ao modo GUI (automação de desktop). Use os modos Browser ou CLI em vez disso.

<div align="center">
    <img src="assets/craftbot_readme_features.png" alt="CraftBot Banner" width="1280"/>
	<img src="assets/craftbot_features_custom.png" alt="CraftBot Banner" width="1280"/>
</div>

---


## 🧰 Começando

### Pré-requisitos
- Python **3.10+**
- `git` (necessário para clonar o repositório)
- Uma chave de API do provedor LLM escolhido (OpenAI, Gemini ou Anthropic)
- `Node.js` **18+** (opcional — necessário apenas para a interface no navegador)
- `conda` (opcional — se não for encontrado, o instalador pode instalar o Miniconda automaticamente)

### Qual opção devo usar?

> **Não sabe qual escolher? Use a Opção 1.** Ela cuida de tudo por você.

| | Opção 1 — Serviço | Opção 2 — Conda | Opção 3 — Manual |
|---|---|---|---|
| **Para quem** | A maioria dos usuários, iniciantes, testes | Usuários de Conda que querem ambientes isolados | Usuários avançados, Python personalizado, controle total |
| **Gerencia Python/ambiente automaticamente?** | ✅ Automático | ✅ Automático | ❌ Você gerencia |
| **Roda em segundo plano?** | ✅ Sim, como serviço | ❌ Não | ❌ Não |
| **Como começar** | `python craftbot.py install` | `python install.py --conda` | `python install.py` |

---

### ⭐ Opção 1 — Instalação como serviço (Recomendada)

**Use esta se:** você quer que o CraftBot simplesmente funcione — serviço em segundo plano, início automático no login, atalho na área de trabalho, sem passos manuais.

O `craftbot.py` cuida de tudo: ambiente Python, dependências, gerenciamento de processos em segundo plano e registro de início automático.

```bash
# 1. Clone o repositório
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. Instale, registre o início automático e inicie o CraftBot
python craftbot.py install
```

É isso. O terminal se fecha sozinho, o CraftBot roda em segundo plano e o navegador abre automaticamente. Um **atalho na área de trabalho** é criado para que você possa reabrir o navegador a qualquer momento.

**Gerenciando o serviço após a instalação:**

```bash
python craftbot.py start      # Iniciar o CraftBot em segundo plano
python craftbot.py stop       # Parar o CraftBot
python craftbot.py restart    # Reiniciar o CraftBot
python craftbot.py status     # Verificar se está rodando e se o início automático está ativo
python craftbot.py logs       # Ver o log recente
```

> [!TIP]
> Após `install` ou `start`, um **atalho do CraftBot na área de trabalho** é criado automaticamente. Se você fechar o navegador, basta dar um duplo clique no atalho para reabri-lo.

---

### Opção 2 — Instalação com Conda

**Use esta se:** você já usa conda e quer o CraftBot em um ambiente conda isolado.

O `install.py --conda` configura um ambiente conda dedicado `craftbot`. Se o Miniconda não for encontrado no seu sistema, ele será instalado automaticamente.

```bash
# 1. Clone o repositório
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. Instale em um ambiente conda
python install.py --conda

# 3. Execute o CraftBot
conda run -n craftbot python run.py

# Se o conda não estiver no PATH (somente Windows):
&"$env:USERPROFILE\miniconda3\Scripts\conda.exe" run -n craftbot python run.py
```

> [!NOTE]
> Sempre que quiser rodar o CraftBot, use `conda run -n craftbot python run.py`. Não há serviço em segundo plano — você inicia e para manualmente.

---

### Opção 3 — Instalação manual (pip)

**Use esta se:** você quer controle total sobre seu ambiente Python e prefere gerenciar o CraftBot por conta própria, sem serviço automático ou processo em segundo plano.

O `install.py` (sem flags) faz uma instalação pip padrão no ambiente Python ativo. Você inicia e para o CraftBot manualmente com `run.py`.

```bash
# 1. Clone o repositório
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. Instale as dependências no seu ambiente Python ativo
python install.py

# 3. Execute o CraftBot
python run.py
```

Na primeira execução, você será guiado para configurar suas chaves de API e preferências.

> [!NOTE]
> Se o Node.js não estiver instalado, o instalador fornecerá instruções passo a passo. Você também pode pular completamente o modo navegador e usar o modo CLI — sem Node.js: `python run.py --cli`

### O que você pode fazer logo de cara?
- Conversar com o agente de forma natural
- Pedir que ele execute tarefas complexas de várias etapas
- Digitar `/help` para ver os comandos disponíveis
- Conectar-se ao Google, Slack, Notion e muito mais

### 🖥️ Modos de interface

<div align="center">
    <img src="assets/WCA_README_banner.png" alt="CraftOS Banner" width="1280"/>
</div>

O CraftBot oferece vários modos de UI. Escolha conforme sua preferência:

| Modo | Comando | Requisitos | Indicado para |
|------|---------|--------------|----------|
| **Browser** | `python run.py` | Node.js 18+ | Interface web moderna, a mais fácil de usar |
| **CLI** | `python run.py --cli` | Nenhum | Linha de comando, leve |

O **modo Browser** é o padrão e recomendado. Se não tiver o Node.js, o instalador fornecerá instruções de instalação, ou você pode usar o **modo CLI**.

---

## 🧬 Living UI

**Living UI é um sistema/app/dashboard que evolui com suas necessidades.**

Precisa de um quadro kanban com um copiloto de IA embutido? Um CRM personalizado
moldado exatamente para o seu fluxo de trabalho? Um dashboard corporativo que o
CraftBot possa ler e operar por você? Coloque-o no ar como uma Living UI — ela
roda junto ao CraftBot e cresce conforme suas necessidades mudam.

<div align="center">
    <img src="assets/living-ui-example.png" alt="Living UI example" width="1280"/>
</div>

### Três formas de criar uma Living UI

1. **Construir do zero.** Descreva o que você quer em linguagem natural. O CraftBot
   monta o modelo de dados, a API do backend e a UI em React, e itera com você
   por meio de um processo de design estruturado.

<div align="center">
    <img src="assets/living-ui-custom-build.png" alt="Building a Living UI from scratch" width="448"/>
</div>

2. **Instalar do marketplace.** Explore Living UIs criadas pela comunidade em [living-ui-marketplace](https://github.com/CraftOS-dev/living-ui-marketplace).

<div align="center">
    <img src="assets/living-ui-marketplace.png" alt="Living UI marketplace" width="448"/>
</div>

3. **Importar um projeto existente.** Aponte o CraftBot para um código-fonte ou
   repositório do GitHub em Go, Node.js, Python, Rust ou estático. Ele detecta o
   runtime, configura os health checks e o empacota como uma Living UI.

<div align="center">
    <img src="assets/living-ui-import.png" alt="Importing an existing project as a Living UI" width="448"/>
</div>

### Continua evoluindo com o CraftBot dentro do loop

Uma Living UI nunca está "pronta". Peça ao agente para adicionar funcionalidades,
redesenhar uma visualização ou conectá-la a novos dados conforme suas necessidades
crescem.

O CraftBot está integrado a cada Living UI e é **consciente do seu estado**:
ele pode ler o DOM atual e os valores de formulário, consultar dados do app
pela API REST, e disparar ações em seu nome.

---

## 🧩 Visão geral da arquitetura

| Componente | Descrição |
|-----------|-------------|
| **Agent Base** | Camada central de orquestração que gerencia o ciclo de vida das tarefas, coordena os componentes e cuida do loop principal do agente. |
| **LLM Interface** | Interface unificada com suporte a vários provedores de LLM (OpenAI, Gemini, Anthropic, BytePlus, Ollama). |
| **Context Engine** | Gera prompts otimizados com suporte a KV-cache. |
| **Action Manager** | Recupera e executa ações da biblioteca. Ações personalizadas são fáceis de estender. |
| **Action Router** | Seleciona de forma inteligente a ação que melhor corresponde aos requisitos da tarefa e resolve parâmetros de entrada via LLM quando necessário. |
| **Event Stream** | Sistema de publicação de eventos em tempo real para acompanhar o progresso das tarefas, atualizar a UI e monitorar a execução. |
| **Memory Manager** | Memória semântica baseada em RAG usando o ChromaDB. Lida com chunking, embeddings, recuperação e atualizações incrementais. |
| **State Manager** | Gerenciamento global de estado para rastrear contexto de execução do agente, histórico de conversas e configurações de runtime. |
| **Task Manager** | Gerencia definições de tarefas, habilita modos simples e complexos, cria to-dos e rastreia workflows multi-etapa. |
| **Skill Manager** | Carrega e injeta skills plugáveis no contexto do agente. |
| **MCP Adapter** | Integração com o Model Context Protocol que converte ferramentas MCP em ações nativas. |

---

## 🔜 Roadmap

- [X] **Módulo de memória** — Concluído.
- [ ] **Integração com ferramentas externas** — Ainda adicionando mais!
- [X] **Camada MCP** — Concluída.
- [X] **Camada de Skills** — Concluída.
- [ ] **Comportamento proativo** — Em andamento

---

## 📋 Referência de comandos

### install.py

| Flag | Descrição |
|------|-------------|
| `--conda` | Usa ambiente conda (opcional) |

### run.py

| Flag | Descrição |
|------|-------------|
| (nenhum) | Executa no modo **Browser** (recomendado, requer Node.js) |
| `--cli` | Executa no modo **CLI** (leve) |

### craftbot.py

| Comando | Descrição |
|---------|-------------|
| `install` | Instala deps, registra auto-start e inicia o CraftBot |
| `start` | Inicia o CraftBot em segundo plano |
| `stop` | Para o CraftBot |
| `restart` | Para e inicia novamente |
| `status` | Mostra o status de execução e do auto-start |
| `logs [-n N]` | Mostra as últimas N linhas do log (padrão: 50) |

**Exemplos de instalação:**
```bash
# Instalação simples via pip (sem conda)
python install.py

# Com ambiente conda (recomendado para usuários de conda)
python install.py --conda
```

**Executando o CraftBot:**

```powershell
# Modo Browser (padrão, requer Node.js)
python run.py

# Modo CLI (leve)
python run.py --cli

# Com ambiente conda
conda run -n craftbot python run.py

# Ou usando caminho completo se o conda não estiver no PATH
&"$env:USERPROFILE\miniconda3\Scripts\conda.exe" run -n craftbot python run.py
```

**Linux/macOS (Bash):**
```bash
# Modo Browser (padrão, requer Node.js)
python run.py

# Modo CLI (leve)
python run.py --cli

# Com ambiente conda
conda run -n craftbot python run.py
```

### 🔧 Serviço em segundo plano (recomendado)

Execute o CraftBot como um serviço em segundo plano para que ele continue rodando mesmo após fechar o terminal. Um atalho na área de trabalho é criado automaticamente, permitindo reabrir o navegador a qualquer momento.

```bash
# Instala dependências, registra auto-start no login e inicia o CraftBot
python craftbot.py install
```

É isso. O terminal se fecha sozinho, o CraftBot roda em segundo plano e o navegador abre automaticamente.

```bash
# Outros comandos do serviço:
python craftbot.py start    # Inicia o CraftBot em segundo plano
python craftbot.py status   # Verifica se está em execução
python craftbot.py stop     # Para o CraftBot
python craftbot.py restart  # Reinicia o CraftBot
python craftbot.py logs     # Mostra logs recentes
```

| Comando | Descrição |
|---------|-------------|
| `python craftbot.py install` | Instala dependências, registra auto-start no login, inicia o CraftBot, abre o navegador e fecha o terminal automaticamente |
| `python craftbot.py start` | Inicia o CraftBot em segundo plano — reinicia automaticamente se já estiver rodando (o terminal se fecha sozinho) |
| `python craftbot.py stop` | Para o CraftBot |
| `python craftbot.py restart` | Para e inicia o CraftBot |
| `python craftbot.py status` | Verifica se o CraftBot está rodando e se o auto-start está habilitado |
| `python craftbot.py logs` | Mostra a saída recente do log (`-n 100` para mais linhas) |

> [!TIP]
> Após `craftbot.py start` ou `craftbot.py install`, um **atalho do CraftBot na área de trabalho** é criado automaticamente. Se você fechar o navegador por acidente, basta clicar duas vezes no atalho para reabri-lo.

> [!NOTE]
> **Instalação:** O instalador agora fornece orientações claras se faltarem dependências. Se o Node.js não for encontrado, você será orientado a instalá-lo ou poderá alternar para o modo CLI. A instalação detecta automaticamente a disponibilidade de GPU e recorre ao modo somente CPU quando necessário.

> [!TIP]
> **Configuração inicial:** O CraftBot vai guiá-lo por um onboarding para configurar chaves de API, o nome do agente, MCPs e Skills.

> [!NOTE]
> **Playwright Chromium:** Opcional para a integração com o WhatsApp Web. Se a instalação falhar, o agente continuará funcionando normalmente para outras tarefas. Instale manualmente depois com: `playwright install chromium`

---

## 🔧 Solução de problemas e dúvidas comuns

### Node.js ausente (para o modo navegador)
Se aparecer **"npm not found in PATH"** ao executar `python run.py`:
1. Baixe em [nodejs.org](https://nodejs.org/) (escolha a versão LTS)
2. Instale e reinicie o terminal
3. Execute `python run.py` novamente

**Alternativa:** Use o modo CLI (sem necessidade de Node.js):
```bash
python run.py --cli
```

### A instalação falha nas dependências
O instalador agora fornece mensagens de erro detalhadas com soluções. Se a instalação falhar:
- **Verifique a versão do Python:** tenha o Python 3.10+ (`python --version`)
- **Verifique sua internet:** as dependências são baixadas durante a instalação
- **Limpe o cache do pip:** `pip install --upgrade pip` e tente de novo

### Problemas com a instalação do Playwright
A instalação do Playwright Chromium é opcional. Se falhar:
- O agente **continuará funcionando** para outras tarefas
- Você pode pular ou instalar depois: `playwright install chromium`
- Só é necessário para a integração com o WhatsApp Web

Para uma solução detalhada, veja [INSTALLATION_FIX.md](INSTALLATION_FIX.md).

---

## 🔌 Integração com serviços externos

O agente pode se conectar a diversos serviços via OAuth. As builds de release vêm com credenciais embutidas, mas você também pode usar as suas.

### Início rápido

Para builds de release com credenciais embutidas:
```
/google login    # Conectar ao Google Workspace
/zoom login      # Conectar ao Zoom
/slack invite    # Conectar ao Slack
/notion invite   # Conectar ao Notion
/linkedin login  # Conectar ao LinkedIn
```

### Detalhes do serviço

| Serviço | Tipo de auth | Comando | Requer segredo? |
|---------|-----------|---------|------------------|
| Google | PKCE | `/google login` | Não (PKCE) |
| Zoom | PKCE | `/zoom login` | Não (PKCE) |
| Slack | OAuth 2.0 | `/slack invite` | Sim |
| Notion | OAuth 2.0 | `/notion invite` | Sim |
| LinkedIn | OAuth 2.0 | `/linkedin login` | Sim |

### Usando suas próprias credenciais

Se preferir usar suas próprias credenciais OAuth, adicione-as ao arquivo `.env`:

#### Google (PKCE — apenas Client ID)
```bash
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
```
1. Acesse o [Google Cloud Console](https://console.cloud.google.com/)
2. Habilite as APIs de Gmail, Calendar, Drive e People
3. Crie credenciais OAuth do tipo **Desktop app**
4. Copie o Client ID (o secret não é necessário com PKCE)

#### Zoom (PKCE — apenas Client ID)
```bash
ZOOM_CLIENT_ID=your-zoom-client-id
```
1. Acesse o [Zoom Marketplace](https://marketplace.zoom.us/)
2. Crie um app OAuth
3. Copie o Client ID

#### Slack (requer ambos)
```bash
SLACK_SHARED_CLIENT_ID=your-slack-client-id
SLACK_SHARED_CLIENT_SECRET=your-slack-client-secret
```
1. Acesse o [Slack API](https://api.slack.com/apps)
2. Crie um novo app
3. Adicione os escopos OAuth: `chat:write`, `channels:read`, `users:read` etc.
4. Copie o Client ID e o Client Secret

#### Notion (requer ambos)
```bash
NOTION_SHARED_CLIENT_ID=your-notion-client-id
NOTION_SHARED_CLIENT_SECRET=your-notion-client-secret
```
1. Acesse o [Notion Developers](https://developers.notion.com/)
2. Crie uma nova integração (Public integration)
3. Copie o OAuth Client ID e o Secret

#### LinkedIn (requer ambos)
```bash
LINKEDIN_CLIENT_ID=your-linkedin-client-id
LINKEDIN_CLIENT_SECRET=your-linkedin-client-secret
```
1. Acesse o [LinkedIn Developers](https://developer.linkedin.com/)
2. Crie um app
3. Adicione os escopos OAuth 2.0
4. Copie o Client ID e o Client Secret

---
## 🐳 Executar com contêiner

A raiz do repositório inclui uma configuração Docker com Python 3.10, pacotes de sistema essenciais (incluindo Tesseract para OCR) e todas as dependências Python definidas em `environment.yml`/`requirements.txt`, para que o agente execute de forma consistente em ambientes isolados.

Abaixo estão as instruções de configuração para rodar nosso agente em contêiner.

### Construir a imagem

Na raiz do repositório:

```bash
docker build -t craftbot .
```

### Executar o contêiner

A imagem está configurada para iniciar o agente com `python -m app.main` por padrão. Para executar interativamente:

```bash
docker run --rm -it craftbot
```

Se precisar fornecer variáveis de ambiente, passe um arquivo env (por exemplo, baseado em `.env.example`):

```bash
docker run --rm -it --env-file .env craftbot
```

Monte quaisquer diretórios que devam persistir fora do contêiner (como pastas de dados ou cache) usando `-v`, e ajuste portas e outras flags conforme necessário para sua implantação. A imagem traz dependências de sistema para OCR (`tesseract`) e clientes HTTP comuns, para que o agente trabalhe com arquivos e APIs de rede dentro do contêiner.

Por padrão, a imagem usa Python 3.10 e empacota as dependências Python de `environment.yml`/`requirements.txt`, portanto `python -m app.main` funciona de imediato.

---

## 🤝 Como contribuir

PRs são bem-vindos! Consulte [CONTRIBUTING.md](CONTRIBUTING.md) para o fluxo (fork → branch a partir de `dev` → PR). Todos os pull requests passam automaticamente por lint + smoke-test no CI. Para dúvidas ou uma conversa mais rápida, entre no nosso [Discord](https://discord.gg/ZN9YHc37HG) ou envie e-mail para thamyikfoong(at)craftos.net.

## 🧾 Licença

Este projeto está licenciado sob a [Licença MIT](LICENSE). Você é livre para usar, hospedar e monetizar este projeto (é necessário dar crédito ao projeto em caso de distribuição e monetização).

---

## ⭐ Agradecimentos

Desenvolvido e mantido por [CraftOS](https://craftos.net/) e pelos contribuidores [@zfoong](https://github.com/zfoong) e [@ahmad-ajmal](https://github.com/ahmad-ajmal).
Se o **CraftBot** é útil para você, por favor dê uma ⭐ no repositório e compartilhe com outras pessoas!

---

## Star History

<a href="https://www.star-history.com/?repos=CraftOS-dev%2FCraftBot&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
 </picture>
</a>
