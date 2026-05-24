<div align="center">
    <a href="https://www.youtube.com/watch?v=8GpdW-gJrDA&autoplay=1" target="_blank">
        <img src="https://img.youtube.com/vi/8GpdW-gJrDA/maxresdefault.jpg" alt="CraftBot Demo Video" width="1280"/>
    </a>
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

## 🧰 Primeiros passos

Requisitos: Python 3.10+ · Node.js 18+ para o modo navegador

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

- Precisa de um quadro kanban com um copiloto de IA embutido?
- Um CRM sob medida, exatamente no formato do seu fluxo de trabalho?
- Um dashboard corporativo que o CraftBot consegue ler e operar por você?

Coloque-o no ar como uma Living UI que roda lado a lado com o CraftBot e cresce conforme suas necessidades mudam.

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

**[Explore e contribua para o marketplace de Living UI →](https://craftos.net/marketplace)**

---
 
# CraftBot vs. as alternativas
 
|                                  | v0 / Lovable / Bolt | OpenClaw | Claude Code | **CraftBot**                            |
| -------------------------------- | ------------------- | -------------------- | -------------------- | --------------------------------------- |
| **Constrói apps personalizados**           | ✅ De uma vez         | 🚫                   | ✅ (manual)          | ✅ Conversacional                       |
| **O agente opera o app**       | 🚫                  | ⚠️ Chama ferramentas      | 🚫                   | ✅ Embutido em toda Living UI         |
| **Memória persistente do agente**      | 🚫                  | ✅            | ✅                   | ✅ RAG + sistema de arquivos do agente + destilação        |
| **Self-hosted**     | ⚠️ Parcial         | ✅                   | 🚫 SaaS              | ✅ MIT, na sua máquina                    |
| **Independente de modelo**     | ✅         | ✅                   | ⚠️ Parcial              | ✅ Principais provedores + OpenRouter                    |
 
---

## 🔧 Solução de problemas e dúvidas comuns

### Falta o Node.js (para o modo navegador)
Se ao rodar `python run.py` você vir **"npm not found in PATH"**:
1. Baixe a versão LTS em [nodejs.org](https://nodejs.org/)
2. Instale e reinicie o terminal
3. Rode `python run.py` novamente

**Alternativa:** Use o modo TUI, que não precisa de Node.js:
```bash
python run.py --tui
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
