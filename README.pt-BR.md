<div align="center">
    <img src="assets/README_banner.png" alt="CraftBot Banner" width="1280"/>
</div>

<div align="center">
    <img src="assets/craftbot_logo_text_small.png" alt="CraftBot" width="400"/>
</div>

A maioria dos frameworks de agentes para por aí: chat e chamadas de ferramenta. O CraftBot vai além: ele constrói, evolui e opera suas próprias ferramentas SaaS, e usa essa camada de ferramentas para se comunicar com você e automatizar tarefas.

Além disso, o CraftBot tem todas as capacidades essenciais de um framework de agente de uso geral. Ele executa tarefas como faria um funcionário remoto, lembra das suas preferências e objetivos, e te ajuda de forma proativa a planejar e agir naquilo que importa.

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
  <a href="README.md">English</a> | <a href="README.ja.md">日本語</a> | <a href="README.cn.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ko.md">한국어</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.de.md">Deutsch</a>
</p>

## ✨ Principais recursos

Além de ser um agente de IA capaz de criar e operar suas próprias ferramentas SaaS, o CraftBot conta com todas as capacidades essenciais de um framework de agente, podendo atuar como um agente de IA de uso geral que te acompanha em suas tarefas, ferramentas, memória e fluxos de trabalho do dia a dia.

- **Living UI.** Construa, importe ou evolua aplicações personalizadas que vivem dentro do CraftBot. O agente conhece o estado atual da UI o tempo todo e pode ler, escrever e agir sobre seus dados diretamente.
- **Multitarefa e roteamento de sessões.** Ainda digitando `/new` manualmente? O CraftBot decide quando abrir uma nova sessão e quando retomar uma tarefa, mantendo conversa e contexto unificados.
- **Self-hosted e BYOK.** Sistema flexível de provedores de LLM com suporte a OpenAI, Google Gemini, Anthropic Claude, OpenRouter e mais. Ou hospede seu próprio modelo gastando 0 tokens com o Ollama.
- **Sistema de memória.** Uma base de conhecimento local construída a partir da sua interação com o CraftBot via RAG + sistema de arquivos do agente + destilação. À meia-noite, o CraftBot "sonha" e consolida os eventos do dia.
- **Agente proativo.** Aprende suas preferências, hábitos e objetivos de vida. Em seguida, planeja e inicia tarefas (com sua aprovação, claro) para te ajudar a evoluir.
- **Integração com ferramentas externas.** Conecte-se a Google Workspace, Slack, Notion, Zoom, LinkedIn, Discord e Telegram (e muito mais por vir!), com credenciais embutidas e suporte a OAuth.
- **Skills e MCP.** Mais de 150 MCPs e 170 Skills prontos para uso. Instalação rápida de novos Skills e MCPs. Crie ou melhore Skills a partir de tarefas concluídas com um clique.
- **Multiplataforma.** Suporte completo a Windows, macOS e Linux, com variantes de código por plataforma e containerização via Docker.
- **Interface de navegador e suporte a CLI.** Use o CraftBot do jeito que melhor te servir: pela UI simples no navegador para o dia a dia, ou via CLI para scripts e ambientes headless.

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

# 2. Instale, registre o autoinício e inicie o CraftBot
python craftbot.py install
```

Pronto. O terminal se fecha sozinho, o CraftBot roda em segundo plano e o navegador abre automaticamente. Um **atalho na área de trabalho** também é criado para que você possa reabrir o navegador quando quiser.

**Gerenciando o serviço após a instalação:**

```bash
python craftbot.py start      # Inicia o CraftBot em segundo plano
python craftbot.py stop       # Para o CraftBot
python craftbot.py restart    # Reinicia o CraftBot
python craftbot.py status     # Verifica se está rodando e se o autoinício está ativo
python craftbot.py logs       # Exibe a saída recente dos logs
python craftbot.py uninstall  # Para o serviço, remove o autoinício e desinstala os pacotes
```

> [!TIP]
> Depois de `install` ou `start`, um **atalho do CraftBot na área de trabalho** é criado automaticamente. Se você fechar o navegador, basta dar duplo clique no atalho para abri-lo de novo.

---

## 🌱 Living UI

**Living UI é um sistema/app/dashboard que evolui junto com suas necessidades.**

<div align="center">
    <img src="assets/living_ui_banner.gif" alt="CraftBot Banner" width="1280"/>
</div>

- Precisa de um quadro kanban com um copiloto de IA embutido?
- Um CRM sob medida, exatamente no formato do seu fluxo de trabalho?
- Um dashboard corporativo que o CraftBot consegue ler e operar por você?

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

### Três jeitos de criar uma Living UI

1. **Construir do zero.** Descreva em linguagem natural o que você quer. O CraftBot
   monta o modelo de dados, a API de back-end e a UI em React, e itera com você
   por um processo de design estruturado.

<div align="center">
    <img src="assets/living-ui-custom-build.png" alt="Building a Living UI from scratch" width="448"/>
</div>

2. **Instalar pelo marketplace.** Explore as Living UIs criadas pela comunidade em [living-ui-marketplace](https://github.com/CraftOS-dev/living-ui-marketplace).

<div align="center">
    <img src="assets/living-ui-marketplace.png" alt="Living UI marketplace" width="448"/>
</div>

3. **Importar um projeto existente.** Aponte o CraftBot para um projeto em Go, Node.js, Python,
   Rust, ou um código-fonte estático ou repositório do GitHub. Ele detecta o runtime, configura health checks e empacota tudo como uma Living UI.

<div align="center">
    <img src="assets/living-ui-import.png" alt="Importing an existing project as a Living UI" width="448"/>
</div>

### Continua evoluindo com o CraftBot dentro do loop

Uma Living UI nunca está "pronta". Peça ao agente para adicionar funcionalidades,
redesenhar uma tela ou conectar a novos dados conforme suas necessidades crescem.

O CraftBot está embutido em toda Living UI e **conhece o estado dela**:
ele consegue ler o DOM atual e os valores dos formulários, consultar os dados da
app via API REST e disparar ações em seu nome.

### Mantém as ferramentas SaaS abertas e vivas

Construa, personalize e evolua sua própria Living UI, e dependa menos de ferramentas por assinatura que nunca foram feitas para encaixar perfeitamente nas suas necessidades.

Estamos ativamente procurando desenvolvedores que queiram mostrar suas Living UIs e exportá-las para o **[marketplace de Living UI](https://craftos.net/marketplace)**. PRs são bem-vindos!

---
 
# Três Living UIs para experimentar em 5 minutos
 
- **📋 Quadro Kanban** — Toda tarefa, follow-up e CTA em um único lugar. O CraftBot pode operá-lo e fazer o trabalho de PM por você.
- **📊 Habit Tracker** — Crie e acompanhe seus hábitos. Calendário de atividades no estilo do GitHub para acompanhar seus hábitos como um(a) dev.
- **🐦 Luolinglo** — Não é o Duolingo, mas você pode aprender novos idiomas, criar flashcards e praticar com o CraftBot.

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
| `uninstall` | Remove o registro do auto-start |

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
| `python craftbot.py uninstall` | Para o CraftBot, remove o registro de auto-start, desinstala pacotes pip e limpa o cache do pip |

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

### Falta o Node.js (para o modo navegador)
Se ao rodar `python run.py` você vir **"npm not found in PATH"**:
1. Baixe a versão LTS em [nodejs.org](https://nodejs.org/)
2. Instale e reinicie o terminal
3. Rode `python run.py` novamente

**Alternativa:** Use o modo CLI (sem necessidade de Node.js):
```bash
python run.py --cli
```

### A instalação falha por dependências
O instalador agora exibe mensagens detalhadas com possíveis soluções. Se a instalação falhar:
- **Verifique a versão do Python:** confirme que tem Python 3.10+ (`python --version`)
- **Verifique a internet:** as dependências são baixadas durante a instalação
- **Limpe o cache do pip:** rode `pip install --upgrade pip` e tente novamente

### Problemas na instalação do Playwright
A instalação do Chromium do Playwright é opcional. Se falhar:
- O agente **continua funcionando** para outras tarefas
- Você pode pular essa etapa e instalar depois com `playwright install chromium`
- Só é necessário para a integração com o WhatsApp Web

Para uma solução de problemas mais detalhada, veja [INSTALLATION_FIX.md](INSTALLATION_FIX.md).

---
## 🐳 Rodar com container

A raiz do repositório inclui uma configuração Docker com Python 3.10, pacotes de sistema essenciais (incluindo Tesseract para OCR) e todas as dependências Python definidas em `environment.yml`/`requirements.txt`, para que o agente rode de forma consistente em ambientes isolados.

Abaixo estão as instruções para rodar nosso agente em container.

### Construir a imagem

A partir da raiz do repositório:

```bash
docker build -t craftbot .
```

### Executar o container

A imagem está configurada para iniciar o agente com `python -m app.main` por padrão. Para rodar de forma interativa:

```bash
docker run --rm -it craftbot
```

Se precisar passar variáveis de ambiente, use um arquivo env (por exemplo, baseado em `.env.example`):

```bash
docker run --rm -it --env-file .env craftbot
```

Monte com `-v` os diretórios que precisam persistir fora do container (por exemplo, pastas de dados ou cache) e ajuste portas ou outras flags conforme seu deploy. A imagem traz dependências de sistema para OCR (`tesseract`) e clientes HTTP comuns, para o agente trabalhar com arquivos e APIs de rede dentro do container.

Por padrão, a imagem usa Python 3.10 e empacota as dependências Python de `environment.yml`/`requirements.txt`, então `python -m app.main` funciona de cara.

---

## 🤝 Como contribuir

PRs são bem-vindos! Confira o fluxo (fork → branch a partir de `dev` → PR) em [CONTRIBUTING.md](CONTRIBUTING.md). Todos os pull requests passam automaticamente por CI de lint + smoke test.

> [!IMPORTANT]
> O **CraftBot** está em desenvolvimento ativo, com melhorias toda semana. Se tiver dúvidas ou quiser uma conversa mais rápida, entre no nosso [Discord](https://discord.gg/ZN9YHc37HG) ou escreva para thamyikfoong(at)craftos.net.

---

## 🧾 Licença

Este projeto está sob a [Licença MIT](LICENSE). Você é livre para usar, hospedar e monetizar este projeto (em caso de distribuição e monetização, é necessário dar crédito a ele).

---

## ⭐ Agradecimentos

Desenvolvido e mantido por [CraftOS](https://craftos.net/) e contribuidores.
Se o **CraftBot** te for útil, dê uma ⭐ no repositório e compartilhe com outras pessoas!

---

## Histórico de stars

<a href="https://www.star-history.com/?repos=CraftOS-dev%2FCraftBot&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
 </picture>
</a>
