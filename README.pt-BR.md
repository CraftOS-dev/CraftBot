<div align="center">
    <img src="assets/README_cover.png" alt="CraftBot" width="1280"/>
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

  <a href="https://deepwiki.com/CraftOS-dev/CraftBot">
    <img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki">
  </a>
</p>

<div align="center">
	
[![SPONSORED BY E2B FOR STARTUPS](https://img.shields.io/badge/SPONSORED%20BY-E2B%20FOR%20STARTUPS-ff8800?style=for-the-badge)](https://e2b.dev/startups)
</div>

<p align="center">
  <a href="README.md">English</a> | <a href="README.ja.md">日本語</a> | <a href="README.cn.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ko.md">한국어</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.de.md">Deutsch</a>
</p>

## ✨ Principais recursos

Além de ser um agente de IA capaz de criar e operar suas próprias ferramentas SaaS, o CraftBot conta com todas as capacidades essenciais de um framework de agente, podendo atuar como um agente de IA de uso geral que te acompanha em suas tarefas, ferramentas, memória e fluxos de trabalho do dia a dia.

- **Perfis de agente** Mais de 40 perfis de agente (agente CEO, agente financeiro, agente líder de marketing, engenheiro DevOps, agente produtor de vídeo e mais 37) prontos para trabalhar por você. Encontre os papéis desejados em **[CraftBot Agent Bundles](https://github.com/CraftOS-dev/craftbot-agent-bundles)** e importe-os com um clique.
- **Catálogo de playbooks** Não sabe como automatizar com agente de IA? O CraftBot tem 120 playbooks prontos para uso (em 19 categorias). Abra o seletor de playbooks pela barra superior, escolha um playbook e ele começa a executar a tarefa por você.
- **Agent App.** Construa, importe ou evolua aplicações personalizadas que vivem dentro do CraftBot. O agente conhece o estado atual da UI o tempo todo e pode ler, escrever e agir sobre seus dados diretamente.
- **Multitarefa e roteamento de sessões.** Ainda digitando `/new` manualmente? O CraftBot decide quando abrir uma nova sessão e quando retomar uma tarefa, mantendo conversa e contexto unificados.
- **Self-hosted e BYOK.** Sistema flexível de provedores de LLM com suporte a OpenAI, Google Gemini, Anthropic Claude, OpenRouter e mais. Ou hospede seu próprio modelo gastando 0 tokens com o Ollama.
- **Sistema de memória.** Um segundo cérebro construído a partir das suas interações com o CraftBot. Abordagem híbrida: RAG + grafo de conhecimento + sistema de arquivos do agente. À meia-noite, o CraftBot "sonha" e consolida os eventos do dia.
- **Agente proativo.** Aprende suas preferências, hábitos e objetivos de vida. Em seguida, planeja e inicia tarefas (com sua aprovação, claro) para te ajudar a evoluir.
- **Integração com ferramentas externas.** Conecte-se aos seus apps como Google Workspace, Slack, Notion, Zoom, LinkedIn, Discord, Telegram e mais (e muito mais por vir!), com suporte a OAuth ou usando sua própria chave. Você pode conectar várias contas a cada integração.
- **Skills e MCP.** Mais de 150 MCPs e 170 Skills prontos para uso. Instalação rápida de novos Skills e MCPs. Crie ou melhore Skills a partir de tarefas concluídas com um clique.
- **Navegador ou terminal.** Use o CraftBot do jeito que melhor te servir: pela UI simples no navegador para o dia a dia, ou pela edição completa para terminal (`python run.py --tui`), com os mesmos chats, configurações e Agent Apps.

---


## 🧰 Começando

**Pré-requisitos**

- Windows 10 ou 11 (x64), macOS 12 ou posterior (Apple Silicon ou Intel), ou Linux (x86_64 ou ARM64)
- Pelo menos 5 GB de espaço livre em disco
- Uma chave de API de um provedor de LLM como OpenAI, Anthropic, Google Gemini ou OpenRouter, ou um modelo local servido pelo Ollama
- Apenas para a instalação pelo código-fonte: Python 3.8 ou posterior. O Node.js não é necessário.

### Opção 1: Instalador (recomendado, sem Python nem Git)

Baixe o arquivo do seu sistema na [versão mais recente](https://github.com/CraftOS-dev/CraftBot/releases/latest):

| Sistema | Arquivo |
|---|---|
| Windows (x64) | `CraftBotInstaller-windows.exe` |
| macOS (Apple Silicon e Intel) | `CraftBotInstaller-macos.zip` |
| Linux (x86_64) | `CraftBotInstaller-linux-x86_64` |
| Linux (ARM64) | `CraftBotInstaller-linux-aarch64` |

Abra o arquivo e clique em **Install CraftBot**. O instalador baixa tudo de que o CraftBot precisa, inicia o CraftBot e o abre no navegador.

Os instaladores ainda não têm assinatura de código, então a primeira execução exige um passo extra:

- **Windows:** se o SmartScreen mostrar "O Windows protegeu o computador", clique em **Mais informações** (More info) e depois em **Executar assim mesmo** (Run anyway).
- **macOS:** descompacte o arquivo e abra `CraftBotInstaller.app`. No macOS 15 ou posterior, a primeira tentativa é bloqueada: abra **Ajustes do Sistema > Privacidade e Segurança**, clique em **Abrir Mesmo Assim** (Open Anyway) ao lado da mensagem sobre o CraftBotInstaller e confirme. No macOS 12 a 14, clique com o botão direito no app e escolha **Abrir** (Open).
- **Linux:** torne o arquivo executável e execute-o a partir de uma sessão de desktop (em um servidor sem desktop, use a instalação pelo código-fonte):
  ```bash
  chmod +x CraftBotInstaller-linux-x86_64
  ./CraftBotInstaller-linux-x86_64
  ```

### Opção 2: Instalar pelo código-fonte

Qualquer Python 3.8 ou posterior que já esteja no seu computador funciona. O CraftBot baixa seu próprio Python 3.10 e Node.js 24 privados e nunca altera o Python ou o Node.js instalados no seu sistema.

```bash
git clone --depth 1 https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot
```

Depois execute o comando de instalação do seu sistema:

```bash
# Windows
python craftbot.py install        # ou: py craftbot.py install

# macOS e Linux
python3 craftbot.py install
```

- **Sem Git?** Na [página do repositório](https://github.com/CraftOS-dev/CraftBot), clique em **Code > Download ZIP**, descompacte, abra um terminal na pasta descompactada e execute o mesmo comando.
- **Sem Python, ou com versão anterior à 3.8?** Use o instalador (opção 1).

A primeira instalação baixa cerca de 1 GB, o que leva alguns minutos em uma conexão comum. Ao terminar, o CraftBot fica rodando em segundo plano, abre http://localhost:7925 no navegador e cria um atalho na área de trabalho. Se a porta 7925 ou 7926 já estiver em uso, o CraftBot escolhe as próximas portas livres e mostra o endereço a abrir.

Na primeira execução, o onboarding no navegador pede sua chave de API do LLM. O CraftBot a guarda em `app/config/settings.json` (você pode alterá-la depois em Configurações) e não lê chaves de API de um arquivo `.env`.

### Gerenciando o CraftBot

Use o mesmo comando `python` ou `python3` da instalação:

```bash
python craftbot.py start      # Inicia o CraftBot em segundo plano
python craftbot.py stop       # Para o CraftBot
python craftbot.py restart    # Reinicia o CraftBot
python craftbot.py status     # Verifica se está rodando e se o autoinício está ativo
python craftbot.py logs       # Mostra as últimas 50 linhas do log (mais com logs -n 200)
python craftbot.py uninstall  # Para, remove o autoinício e desinstala os pacotes
python run.py --tui           # Executa no terminal em vez do navegador
```

Quem usa o instalador pode fazer o mesmo pela janela do instalador (**Start**, **Stop**, **Repair**, **Uninstall**).

> [!TIP]
> Depois de `install` ou `start`, um **atalho do CraftBot na área de trabalho** é criado automaticamente. Se você fechar o navegador, dê um duplo clique no atalho para abri-lo de novo.

---

## 🌱 Agent App

**Agent App é um sistema/app/dashboard que evolui com suas necessidades.**

<div align="center">
    <img src="assets/agent_app_banner.gif" alt="CraftBot Banner" width="1280"/>
</div>

- Precisa de um quadro kanban com um copiloto de IA embutido? 
- Um CRM sob medida, exatamente no formato do seu fluxo de trabalho? 
- Um dashboard corporativo que o CraftBot consegue ler e operar por você? 

Coloque-o no ar como uma Agent App que roda junto ao CraftBot e cresce conforme suas necessidades mudam.

### Três jeitos de criar uma Agent App

1. **Construir do zero.** Descreva em linguagem natural o que você quer. O CraftBot
   monta o modelo de dados, a API de back-end e a UI em React, e itera com
   você por um processo de design estruturado.

<div align="center">
    <img src="assets/agent-app-custom-build.png" alt="Building a Agent App from scratch" width="448"/>
</div>

2. **Instalar pelo marketplace.** Explore as Agent Apps criadas pela comunidade em [living-ui-marketplace](https://github.com/CraftOS-dev/living-ui-marketplace).

<div align="center">
    <img src="assets/living-ui-marketplace.png" alt="Agent App marketplace" width="448"/>
</div>

3. **Importar um projeto existente.** Aponte o CraftBot para um projeto em Go, Node.js, Python,
   Rust, ou um código-fonte estático ou repositório do GitHub. Ele detecta o runtime, configura health checks e empacota tudo como uma Agent App.

<div align="center">
    <img src="assets/agent-app-import.png" alt="Importing an existing project as a Agent App" width="448"/>
</div>

### Continua evoluindo com o CraftBot dentro do loop

Uma Agent App nunca está "pronta". Peça ao agente para adicionar funcionalidades,
redesenhar uma tela ou conectar a novos dados conforme suas necessidades crescem.

O CraftBot está embutido em toda Agent App e **conhece o estado dela**:
ele consegue ler o DOM atual e os valores dos formulários, consultar os dados da
app via API REST e disparar ações em seu nome.

### Mantém as ferramentas SaaS abertas e vivas

Construa, personalize e evolua sua própria Agent App, e dependa menos de ferramentas por assinatura que nunca foram feitas para encaixar perfeitamente nas suas necessidades.

---
 
# Três Agent Apps para experimentar em 5 minutos
 
- **📋 Quadro Kanban**: toda tarefa, follow-up e CTA em um único lugar. O CraftBot pode operá-lo e fazer o trabalho de PM por você.
- **📊 Habit Tracker**: crie e acompanhe seus hábitos. Calendário de atividades no estilo do GitHub para acompanhar seus hábitos como um(a) dev.
- **🐦 Luolinglo**: não é o Duolingo, mas você pode aprender novos idiomas, criar flashcards e praticar com o CraftBot.

**[Explore e contribua com o marketplace de Agent App →](https://craftos.net/marketplace)**

---

## 🔧 Solução de problemas e dúvidas comuns

**Comece pelo log.** `python craftbot.py logs` mostra as últimas 50 linhas (mais com `logs -n 200`). Quando `install` ou `start` falha, o comando mostra o final do log e termina com erro. `python craftbot.py doctor` verifica cada etapa da instalação sem alterar nada. No instalador, clique em **Open log**.

**Executar a instalação de novo é seguro.** `python craftbot.py install` pula as etapas que já deram certo e tenta novamente apenas o restante. No instalador, clique em **Repair**.

### As portas 7925 ou 7926 já estão em uso

O CraftBot passa para as próximas portas livres e mostra o endereço a abrir. Para escolher as portas você mesmo:

```bash
python craftbot.py start --frontend-port 8925 --backend-port 8926
```

### Proxy ou rede corporativa

Todos os downloads (Python, pip, npm, Node.js) usam as variáveis de proxy padrão. Defina-as no mesmo terminal antes de instalar:

```bash
# macOS e Linux
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

Redes que inspecionam o tráfego TLS não exigem nenhum passo extra: o CraftBot confia nos certificados do repositório de certificados do seu sistema operacional.

### Downloads lentos ou bloqueados (por exemplo, na China continental)

Antes de instalar, aponte os downloads para mirrors:

| Variável | Uso | Exemplo |
|---|---|---|
| `PIP_INDEX_URL` | Pacotes Python | `https://pypi.tuna.tsinghua.edu.cn/simple` |
| `npm_config_registry` | Pacotes npm | `https://registry.npmmirror.com` |
| `HF_ENDPOINT` | Modelo de embeddings | `https://hf-mirror.com` |
| `CRAFTBOT_MIRRORS` | Downloads de Python, Node.js, PocketBase e do modelo de embeddings | veja abaixo |

`CRAFTBOT_MIRRORS` é uma lista, separada por ponto e vírgula, de reescritas de URL no formato `prefix=replacement` (prefixo=substituição):

```bash
export CRAFTBOT_MIRRORS="https://github.com/=https://<your-github-proxy>/https://github.com/;https://nodejs.org/dist/=https://npmmirror.com/mirrors/node/"
```

Os pacotes Python e o modelo de embeddings da memória continuam sendo verificados por checksums SHA-256 fixados, então um mirror não consegue alterá-los. Os runtimes de Python e Node.js não são fixados, então use para eles apenas um mirror de confiança. No Windows PowerShell, defina as variáveis com `$env:NAME = "value"` em vez de `export`.

### Servidor sem desktop

Instale pelo código-fonte no servidor sem abrir um navegador:

```bash
python3 craftbot.py install --no-open-browser
```

O CraftBot escuta em `localhost` e só aceita conexões do navegador endereçadas a `localhost`. Para usá-lo no seu próprio computador, abra um túnel SSH que encaminhe as duas portas com os mesmos números e depois abra http://localhost:7925 no seu computador:

```bash
ssh -L 7925:localhost:7925 -L 7926:localhost:7926 user@server
```

`CRAFTBOT_BIND_HOST` faz o CraftBot escutar em outra interface de rede (a imagem Docker usa `0.0.0.0`). Para acesso remoto, o túnel SSH continua sendo o caminho recomendado.

### Linux: o CraftBot não inicia depois de reiniciar

O autoinício é um serviço de usuário do systemd, por isso precisa de uma sessão de usuário do systemd. Para que o CraftBot inicie no boot sem login e continue rodando depois do logout, ative o lingering uma vez:

```bash
loginctl enable-linger $USER
```

Sem systemd (por exemplo, no WSL com o systemd desativado), execute `python3 craftbot.py start` depois de cada boot.

### macOS: o instalador é bloqueado

O instalador ainda não tem assinatura de código. No macOS 15 ou posterior, tente abri-lo uma vez, depois abra **Ajustes do Sistema > Privacidade e Segurança** e clique em **Abrir Mesmo Assim** (Open Anyway). No macOS 12 a 14, clique com o botão direito no app e escolha **Abrir** (Open).

### Windows: o SmartScreen bloqueia o instalador

Clique em **Mais informações** (More info) e depois em **Executar assim mesmo** (Run anyway). O aviso aparece porque o instalador ainda não tem assinatura de código.

### Windows: `python` abre a Microsoft Store

O Python não está instalado. Use o instalador, ou instale o Python pelo [python.org](https://www.python.org/downloads/) e execute `py craftbot.py install`.

### Guardar os dados do CraftBot em outro lugar

Antes de instalar, defina `CRAFTBOT_HOME` com uma pasta para guardar ali todos os dados do CraftBot e os runtimes baixados, por exemplo em um disco maior. O autoinício mantém essa configuração.

### Recursos de navegador (Playwright)

O Mini Browser e a automação do navegador usam o Chromium do Playwright. Se o download dele falhar, o restante do CraftBot continua funcionando. Execute `python craftbot.py install` de novo mais tarde para tentar outra vez.

---

## 🐳 Rodar com container

A imagem Docker executa o CraftBot no modo navegador com tudo pré-instalado: Python 3.10 com as dependências fixadas, Node.js 24, a interface do navegador, o PocketBase e o Chromium do Playwright.

Na raiz do repositório:

```bash
docker compose up -d
```

O primeiro build leva vários minutos. Depois abra http://localhost:7925 e informe sua chave de API do LLM no onboarding.

Configurações e chaves de API, arquivos do agente, memória e logs ficam no volume `craftbot-data`, então são mantidos entre reinícios e novos builds da imagem.

```bash
docker compose logs -f craftbot              # Acompanha o log
docker compose ps                            # Status, incluindo o health check
docker compose down                          # Para (o volume de dados é mantido)
git pull && docker compose up -d --build     # Atualiza para a versão mais recente
```

- As portas são publicadas apenas em `127.0.0.1`, porque a interface do CraftBot não tem login próprio. Em um servidor remoto, mantenha assim e conecte-se pelo túnel SSH descrito em Solução de problemas. Mantenha as portas do host em 7925 e 7926: o CraftBot só aceita conexões do navegador endereçadas a `localhost` nessas portas.
- As configurações de proxy e mirrors (`HTTPS_PROXY`, `PIP_INDEX_URL`, `HF_ENDPOINT`, `CRAFTBOT_MIRRORS` e as demais listadas em `.env.example`) são repassadas ao container quando estão definidas no seu shell ou em um arquivo `.env` ao lado do `docker-compose.yml`.
- As Agent Apps rodam nas portas 3100 a 3199 dentro do container e ainda não podem ser abertas pelo navegador do host. Para trabalhar com Agent Apps, use o instalador ou a instalação pelo código-fonte.
- Sem o Compose:
  ```bash
  docker build -t craftbot .
  docker run -d --name craftbot -p 127.0.0.1:7925:7925 -p 127.0.0.1:7926:7926 --shm-size 1g -v craftbot-data:/data craftbot
  ```

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

<a href="https://star-history.dera.page/#CraftOS-dev/CraftBot&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
 </picture>
</a>
