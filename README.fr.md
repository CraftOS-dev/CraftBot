
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
    <img src="https://img.shields.io/badge/Discord-Rejoindre%20la%20communaut%C3%A9-5865F2?logo=discord&logoColor=white" alt="Discord">
  </a>
<br/>
<br/>

[![SPONSORED BY E2B FOR STARTUPS](https://img.shields.io/badge/SPONSORED%20BY-E2B%20FOR%20STARTUPS-ff8800?style=for-the-badge)](https://e2b.dev/startups)

<a href="https://www.producthunt.com/products/craftbot?embed=true&amp;utm_source=badge-top-post-badge&amp;utm_medium=badge&amp;utm_campaign=badge-craftbot" target="_blank" rel="noopener noreferrer"><img alt="CraftBot - Self-hosted proactive AI assistant that lives locally | Product Hunt" width="250" height="54" src="https://api.producthunt.com/widgets/embed-image/v1/top-post-badge.svg?post_id=1110300&amp;theme=dark&amp;period=daily&amp;t=1776679679509"></a>
</div>

<p align="center">
  <a href="README.md">English</a> | <a href="README.ja.md">日本語</a> | <a href="README.cn.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ko.md">한국어</a> | <a href="README.es.md">Español</a> | <a href="README.pt-BR.md">Português</a> | <a href="README.de.md">Deutsch</a>
</p>

## 🚀 Aperçu
<h3 align="center">
CraftBot est votre Assistant IA Personnel qui vit à l'intérieur de votre machine et travaille 24h/24 pour vous.
</h3>

Il interprète les tâches de manière autonome, planifie les actions et les exécute pour atteindre vos objectifs.
Il apprend vos préférences et objectifs, et vous aide de façon proactive à planifier et lancer des tâches pour atteindre vos buts de vie.
Les MCP, les Skills et les intégrations d'applications externes sont pris en charge.

CraftBot attend vos ordres. Configurez dès maintenant votre propre CraftBot.

<div align="center">
    <img src="assets/craftbot_overview.png" alt="CraftBot Overview" width="1280"/>
</div>

---

## ✨ Fonctionnalités

- **Bring Your Own Key (BYOK)** — Système flexible de fournisseurs LLM prenant en charge OpenAI, Google Gemini, Anthropic Claude, BytePlus et les modèles locaux Ollama. Basculez facilement entre fournisseurs.
- **Système de mémoire** — Distille et consolide les événements de la journée à minuit.
- **Agent proactif** — Apprend vos préférences, habitudes et objectifs de vie. Puis planifie et lance des tâches (avec votre accord, bien sûr) pour vous aider à progresser.
- **Living UI** — Créez, importez ou faites évoluer des applications personnalisées qui vivent au sein de CraftBot. L'agent reste conscient de l'état de l'UI et peut lire, écrire et agir directement sur ses données.
- **Intégration d'outils externes** — Connectez-vous à Google Workspace, Slack, Notion, Zoom, LinkedIn, Discord et Telegram (d'autres à venir !) avec des identifiants intégrés et le support OAuth.
- **MCP** — Intégration du Model Context Protocol pour étendre les capacités de l'agent avec des outils et services externes.
- **Skills** — Framework de skills extensible avec des skills intégrées pour la planification de tâches, la recherche, la revue de code, les opérations git, etc.
- **Multiplateforme** — Prise en charge complète de Windows, macOS et Linux avec des variantes de code spécifiques à chaque plateforme et la conteneurisation Docker.

> [!IMPORTANT]
> **Le mode GUI est déprécié.** CraftBot ne prend plus en charge le mode GUI (automatisation de bureau). Utilisez plutôt le mode Browser ou CLI.

<div align="center">
    <img src="assets/craftbot_readme_features.png" alt="CraftBot Banner" width="1280"/>
	<img src="assets/craftbot_features_custom.png" alt="CraftBot Banner" width="1280"/>
</div>

---


## 🧰 Pour commencer

### Prérequis
- Python **3.10+**
- `git` (nécessaire pour cloner le dépôt)
- Une clé API pour le fournisseur LLM de votre choix (OpenAI, Gemini ou Anthropic)
- `Node.js` **18+** (optionnel — requis uniquement pour l'interface navigateur)
- `conda` (optionnel — s'il est introuvable, l'installateur propose d'installer Miniconda automatiquement)

### Quelle option choisir ?

> **Vous hésitez ? Optez pour l'Option 1.** Elle gère tout pour vous.

| | Option 1 — Service | Option 2 — Conda | Option 3 — Manuel |
|---|---|---|---|
| **Pour qui** | La plupart des utilisateurs, débutants, tests | Utilisateurs Conda souhaitant des environnements isolés | Utilisateurs avancés, Python personnalisé, contrôle total |
| **Gère Python/l'environnement automatiquement ?** | ✅ Automatique | ✅ Automatique | ❌ Vous le gérez |
| **Tourne en arrière-plan ?** | ✅ Oui, en tant que service | ❌ Non | ❌ Non |
| **Comment démarrer** | `python craftbot.py install` | `python install.py --conda` | `python install.py` |

---

### ⭐ Option 1 — Installation en service (Recommandée)

**Choisissez cette option si :** vous voulez que CraftBot fonctionne directement — service en arrière-plan, démarrage automatique à la connexion, raccourci sur le bureau, aucune étape manuelle.

`craftbot.py` gère tout : environnement Python, dépendances, gestion du processus en arrière-plan et enregistrement du démarrage automatique.

```bash
# 1. Clonez le dépôt
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. Installez, enregistrez le démarrage automatique et lancez CraftBot
python craftbot.py install
```

C'est tout. Le terminal se ferme tout seul, CraftBot tourne en arrière-plan et le navigateur s'ouvre automatiquement. Un **raccourci sur le bureau** est créé pour rouvrir le navigateur à tout moment.

**Gestion du service après installation :**

```bash
python craftbot.py start      # Démarrer CraftBot en arrière-plan
python craftbot.py stop       # Arrêter CraftBot
python craftbot.py restart    # Redémarrer CraftBot
python craftbot.py status     # Vérifier s'il tourne et si le démarrage automatique est activé
python craftbot.py logs       # Voir les logs récents
python craftbot.py uninstall  # Arrêter, supprimer le démarrage auto et désinstaller les paquets
```

> [!TIP]
> Après `install` ou `start`, un **raccourci CraftBot sur le bureau** est créé automatiquement. Si vous fermez le navigateur, double-cliquez sur le raccourci pour le rouvrir.

---

### Option 2 — Installation Conda

**Choisissez cette option si :** vous utilisez déjà conda et souhaitez CraftBot dans un environnement conda isolé.

`install.py --conda` configure un environnement conda dédié `craftbot`. Si Miniconda n'est pas trouvé sur votre système, il sera installé automatiquement.

```bash
# 1. Clonez le dépôt
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. Installez dans un environnement conda
python install.py --conda

# 3. Lancez CraftBot
conda run -n craftbot python run.py

# Si conda n'est pas dans le PATH (Windows uniquement) :
&"$env:USERPROFILE\miniconda3\Scripts\conda.exe" run -n craftbot python run.py
```

> [!NOTE]
> Chaque fois que vous voulez lancer CraftBot, utilisez `conda run -n craftbot python run.py`. Il n'y a pas de service en arrière-plan — vous le démarrez et l'arrêtez vous-même.

---

### Option 3 — Installation manuelle (pip)

**Choisissez cette option si :** vous souhaitez un contrôle total sur votre environnement Python et préférez gérer CraftBot vous-même, sans service automatique ni processus en arrière-plan.

`install.py` (sans options) effectue une installation pip standard dans l'environnement Python actif. Vous démarrez et arrêtez CraftBot manuellement avec `run.py`.

```bash
# 1. Clonez le dépôt
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. Installez les dépendances dans votre environnement Python actif
python install.py

# 3. Lancez CraftBot
python run.py
```

La première exécution vous guidera dans la configuration de vos clés API et préférences.

> [!NOTE]
> Si Node.js n'est pas installé, l'installateur fournira des instructions étape par étape. Vous pouvez aussi ignorer complètement le mode navigateur et utiliser le mode CLI — sans Node.js : `python run.py --cli`

### Que pouvez-vous faire tout de suite ?
- Discuter avec l'agent naturellement
- Lui demander d'exécuter des tâches complexes en plusieurs étapes
- Taper `/help` pour voir les commandes disponibles
- Vous connecter à Google, Slack, Notion et plus

### 🖥️ Modes d'interface

<div align="center">
    <img src="assets/WCA_README_banner.png" alt="CraftOS Banner" width="1280"/>
</div>

CraftBot propose plusieurs modes d'UI. Choisissez selon vos préférences :

| Mode | Commande | Prérequis | Idéal pour |
|------|---------|--------------|----------|
| **Browser** | `python run.py` | Node.js 18+ | Interface web moderne, la plus simple à utiliser |
| **CLI** | `python run.py --cli` | Aucun | Ligne de commande, léger |

Le **mode navigateur** est le mode par défaut et recommandé. Si vous n'avez pas Node.js, l'installateur vous guidera pour l'installer, ou vous pouvez utiliser le **mode CLI**.

---

## 🧬 Living UI

**Living UI est un système/une application/un tableau de bord qui évolue avec vos besoins.**

Besoin d'un tableau kanban avec un copilote IA intégré ? D'un CRM sur mesure taillé
exactement pour votre flux de travail ? D'un tableau de bord d'entreprise que CraftBot
peut lire et piloter pour vous ? Lancez-le comme une Living UI — elle tourne aux côtés
de CraftBot et grandit au rythme de vos besoins.

<div align="center">
    <img src="assets/living-ui-example.png" alt="Living UI example" width="1280"/>
</div>

### Trois façons de créer une Living UI

1. **Construire à partir de zéro.** Décrivez ce que vous voulez en langage naturel.
   CraftBot met en place le modèle de données, l'API backend et l'interface React,
   et itère avec vous à travers un processus de conception structuré.

<div align="center">
    <img src="assets/living-ui-custom-build.png" alt="Building a Living UI from scratch" width="448"/>
</div>

2. **Installer depuis la marketplace.** Parcourez les Living UIs créées par la communauté sur [living-ui-marketplace](https://github.com/CraftOS-dev/living-ui-marketplace).

<div align="center">
    <img src="assets/living-ui-marketplace.png" alt="Living UI marketplace" width="448"/>
</div>

3. **Importer un projet existant.** Pointez CraftBot vers un code source ou un dépôt
   GitHub en Go, Node.js, Python, Rust ou statique. Il détecte le runtime, configure
   les vérifications de santé et l'encapsule en Living UI.

<div align="center">
    <img src="assets/living-ui-import.png" alt="Importing an existing project as a Living UI" width="448"/>
</div>

### Continue d'évoluer avec CraftBot dans la boucle

Une Living UI n'est jamais « terminée ». Demandez à l'agent d'ajouter des
fonctionnalités, de repenser une vue ou de la brancher à de nouvelles données
à mesure que vos besoins évoluent.

CraftBot est intégré à chaque Living UI et **conscient de son état** :
il peut lire le DOM courant et les valeurs des formulaires, interroger les
données de l'app via l'API REST, et déclencher des actions en votre nom.

---

## 🧩 Aperçu de l'architecture

| Composant | Description |
|-----------|-------------|
| **Agent Base** | Couche d'orchestration centrale qui gère le cycle de vie des tâches, coordonne les composants et pilote la boucle agentique principale. |
| **LLM Interface** | Interface unifiée prenant en charge plusieurs fournisseurs LLM (OpenAI, Gemini, Anthropic, BytePlus, Ollama). |
| **Context Engine** | Génère des prompts optimisés avec support du cache KV. |
| **Action Manager** | Récupère et exécute les actions depuis la bibliothèque. Les actions personnalisées sont faciles à étendre. |
| **Action Router** | Sélectionne intelligemment l'action la plus adaptée aux exigences de la tâche et résout les paramètres d'entrée via le LLM au besoin. |
| **Event Stream** | Système de publication d'événements en temps réel pour le suivi de la progression des tâches, les mises à jour d'UI et le monitoring d'exécution. |
| **Memory Manager** | Mémoire sémantique basée sur le RAG via ChromaDB. Gère le découpage, l'embedding, la récupération et les mises à jour incrémentales. |
| **State Manager** | Gestion globale de l'état pour suivre le contexte d'exécution de l'agent, l'historique de conversation et la configuration d'exécution. |
| **Task Manager** | Gère les définitions de tâches, permet des modes simples et complexes, crée des to-dos et suit les workflows multi-étapes. |
| **Skill Manager** | Charge et injecte des skills enfichables dans le contexte de l'agent. |
| **MCP Adapter** | Intégration Model Context Protocol qui convertit les outils MCP en actions natives. |

---

## 🔜 Roadmap

- [X] **Module de mémoire** — Terminé.
- [ ] **Intégration d'outils externes** — En cours d'ajout !
- [X] **Couche MCP** — Terminée.
- [X] **Couche Skills** — Terminée.
- [ ] **Comportement proactif** — En cours

---

## 📋 Référence des commandes

### install.py

| Flag | Description |
|------|-------------|
| `--conda` | Utiliser un environnement conda (optionnel) |

### run.py

| Flag | Description |
|------|-------------|
| (aucun) | Lancer en mode **Browser** (recommandé, nécessite Node.js) |
| `--cli` | Lancer en mode **CLI** (léger) |

### craftbot.py

| Commande | Description |
|---------|-------------|
| `install` | Installe les deps, enregistre le démarrage automatique et lance CraftBot |
| `start` | Démarre CraftBot en arrière-plan |
| `stop` | Arrête CraftBot |
| `restart` | Arrête puis redémarre |
| `status` | Affiche l'état d'exécution et celui du démarrage automatique |
| `logs [-n N]` | Affiche les N dernières lignes de log (par défaut : 50) |
| `uninstall` | Supprime l'enregistrement du démarrage automatique |

**Exemples d'installation :**
```bash
# Installation simple via pip (sans conda)
python install.py

# Avec environnement conda (recommandé pour les utilisateurs de conda)
python install.py --conda
```

**Exécuter CraftBot :**

```powershell
# Mode Browser (par défaut, nécessite Node.js)
python run.py

# Mode CLI (léger)
python run.py --cli

# Avec environnement conda
conda run -n craftbot python run.py

# Ou en utilisant le chemin complet si conda n'est pas dans le PATH
&"$env:USERPROFILE\miniconda3\Scripts\conda.exe" run -n craftbot python run.py
```

**Linux/macOS (Bash) :**
```bash
# Mode Browser (par défaut, nécessite Node.js)
python run.py

# Mode CLI (léger)
python run.py --cli

# Avec environnement conda
conda run -n craftbot python run.py
```

### 🔧 Service en arrière-plan (recommandé)

Exécutez CraftBot en tant que service en arrière-plan pour qu'il continue de fonctionner même après la fermeture du terminal. Un raccourci de bureau est créé automatiquement pour rouvrir le navigateur à tout moment.

```bash
# Installer les dépendances, enregistrer le démarrage automatique à la connexion et lancer CraftBot
python craftbot.py install
```

C'est tout. Le terminal se ferme tout seul, CraftBot tourne en arrière-plan et le navigateur s'ouvre automatiquement.

```bash
# Autres commandes du service :
python craftbot.py start    # Démarre CraftBot en arrière-plan
python craftbot.py status   # Vérifie s'il tourne
python craftbot.py stop     # Arrête CraftBot
python craftbot.py restart  # Redémarre CraftBot
python craftbot.py logs     # Affiche les logs récents
```

| Commande | Description |
|---------|-------------|
| `python craftbot.py install` | Installe les dépendances, enregistre le démarrage automatique à la connexion, lance CraftBot, ouvre le navigateur et ferme le terminal automatiquement |
| `python craftbot.py start` | Démarre CraftBot en arrière-plan — redémarre automatiquement s'il est déjà lancé (le terminal se ferme tout seul) |
| `python craftbot.py stop` | Arrête CraftBot |
| `python craftbot.py restart` | Arrête puis démarre CraftBot |
| `python craftbot.py status` | Vérifie si CraftBot tourne et si le démarrage automatique est activé |
| `python craftbot.py logs` | Affiche les logs récents (`-n 100` pour plus de lignes) |
| `python craftbot.py uninstall` | Arrête CraftBot, supprime le démarrage automatique, désinstalle les paquets pip et purge le cache pip |

> [!TIP]
> Après `craftbot.py start` ou `craftbot.py install`, un **raccourci CraftBot sur le bureau** est créé automatiquement. Si vous fermez le navigateur par accident, double-cliquez sur le raccourci pour le rouvrir.

> [!NOTE]
> **Installation :** L'installateur fournit maintenant des indications claires si des dépendances manquent. Si Node.js est introuvable, on vous proposera de l'installer ou de basculer en mode CLI. L'installation détecte automatiquement la disponibilité du GPU et bascule en mode CPU si nécessaire.

> [!TIP]
> **Première configuration :** CraftBot vous guidera dans une séquence d'onboarding pour configurer les clés API, le nom de l'agent, les MCP et les Skills.

> [!NOTE]
> **Playwright Chromium :** Optionnel pour l'intégration WhatsApp Web. Si l'installation échoue, l'agent fonctionnera toujours pour les autres tâches. Installez-le manuellement plus tard avec : `playwright install chromium`

---

## 🔧 Dépannage et problèmes courants

### Node.js manquant (pour le mode navigateur)
Si vous voyez **"npm not found in PATH"** en lançant `python run.py` :
1. Téléchargez depuis [nodejs.org](https://nodejs.org/) (choisissez la version LTS)
2. Installez et redémarrez votre terminal
3. Relancez `python run.py`

**Alternative :** Utilisez le mode CLI (Node.js non requis) :
```bash
python run.py --cli
```

### L'installation échoue sur les dépendances
L'installateur fournit désormais des messages d'erreur détaillés avec des solutions. Si l'installation échoue :
- **Vérifiez la version de Python :** assurez-vous d'avoir Python 3.10+ (`python --version`)
- **Vérifiez votre connexion :** les dépendances sont téléchargées pendant l'installation
- **Videz le cache pip :** `pip install --upgrade pip` puis réessayez

### Problèmes d'installation de Playwright
L'installation de Playwright Chromium est optionnelle. En cas d'échec :
- L'agent **continuera de fonctionner** pour les autres tâches
- Vous pouvez l'ignorer ou l'installer plus tard : `playwright install chromium`
- Nécessaire uniquement pour l'intégration WhatsApp Web

Pour un dépannage détaillé, consultez [INSTALLATION_FIX.md](INSTALLATION_FIX.md).

---

## 🔌 Intégration des services externes

L'agent peut se connecter à divers services via OAuth. Les builds de release incluent des identifiants intégrés, mais vous pouvez aussi utiliser les vôtres.

### Démarrage rapide

Pour les builds de release avec identifiants intégrés :
```
/google login    # Connecter Google Workspace
/zoom login      # Connecter Zoom
/slack invite    # Connecter Slack
/notion invite   # Connecter Notion
/linkedin login  # Connecter LinkedIn
```

### Détails des services

| Service | Type d'auth | Commande | Secret requis ? |
|---------|-----------|---------|------------------|
| Google | PKCE | `/google login` | Non (PKCE) |
| Zoom | PKCE | `/zoom login` | Non (PKCE) |
| Slack | OAuth 2.0 | `/slack invite` | Oui |
| Notion | OAuth 2.0 | `/notion invite` | Oui |
| LinkedIn | OAuth 2.0 | `/linkedin login` | Oui |

### Utiliser vos propres identifiants

Si vous préférez utiliser vos propres identifiants OAuth, ajoutez-les à votre fichier `.env` :

#### Google (PKCE — uniquement le Client ID)
```bash
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
```
1. Allez sur la [Google Cloud Console](https://console.cloud.google.com/)
2. Activez les API Gmail, Calendar, Drive et People
3. Créez des identifiants OAuth de type **Desktop app**
4. Copiez le Client ID (le secret n'est pas requis en PKCE)

#### Zoom (PKCE — uniquement le Client ID)
```bash
ZOOM_CLIENT_ID=your-zoom-client-id
```
1. Allez sur le [Zoom Marketplace](https://marketplace.zoom.us/)
2. Créez une application OAuth
3. Copiez le Client ID

#### Slack (les deux requis)
```bash
SLACK_SHARED_CLIENT_ID=your-slack-client-id
SLACK_SHARED_CLIENT_SECRET=your-slack-client-secret
```
1. Allez sur [Slack API](https://api.slack.com/apps)
2. Créez une nouvelle application
3. Ajoutez les scopes OAuth : `chat:write`, `channels:read`, `users:read`, etc.
4. Copiez le Client ID et le Client Secret

#### Notion (les deux requis)
```bash
NOTION_SHARED_CLIENT_ID=your-notion-client-id
NOTION_SHARED_CLIENT_SECRET=your-notion-client-secret
```
1. Allez sur [Notion Developers](https://developers.notion.com/)
2. Créez une nouvelle intégration (Public integration)
3. Copiez l'OAuth Client ID et le Secret

#### LinkedIn (les deux requis)
```bash
LINKEDIN_CLIENT_ID=your-linkedin-client-id
LINKEDIN_CLIENT_SECRET=your-linkedin-client-secret
```
1. Allez sur [LinkedIn Developers](https://developer.linkedin.com/)
2. Créez une application
3. Ajoutez les scopes OAuth 2.0
4. Copiez le Client ID et le Client Secret

---
## 🐳 Exécuter avec un conteneur

La racine du dépôt contient une configuration Docker avec Python 3.10, des paquets système clés (dont Tesseract pour l'OCR) et toutes les dépendances Python définies dans `environment.yml`/`requirements.txt`, pour que l'agent s'exécute de façon cohérente dans des environnements isolés.

Ci-dessous les instructions pour exécuter notre agent en conteneur.

### Construire l'image

Depuis la racine du dépôt :

```bash
docker build -t craftbot .
```

### Exécuter le conteneur

L'image est configurée pour lancer l'agent avec `python -m app.main` par défaut. Pour l'exécuter en mode interactif :

```bash
docker run --rm -it craftbot
```

Si vous devez fournir des variables d'environnement, passez un fichier env (par exemple basé sur `.env.example`) :

```bash
docker run --rm -it --env-file .env craftbot
```

Montez tous les répertoires qui doivent persister en dehors du conteneur (comme les dossiers de données ou cache) via `-v`, et ajustez les ports ou autres flags selon votre déploiement. L'image embarque les dépendances système pour l'OCR (`tesseract`) et les clients HTTP courants, afin que l'agent puisse travailler avec les fichiers et les API réseau dans le conteneur.

Par défaut, l'image utilise Python 3.10 et embarque les dépendances Python de `environment.yml`/`requirements.txt`, donc `python -m app.main` fonctionne immédiatement.

---

## 🤝 Comment contribuer

Les PR sont les bienvenues ! Voir [CONTRIBUTING.md](CONTRIBUTING.md) pour le workflow (fork → branche depuis `dev` → PR). Toutes les pull requests passent automatiquement par un CI lint + smoke-test. Pour toute question ou une discussion plus rapide, rejoignez-nous sur [Discord](https://discord.gg/ZN9YHc37HG) ou envoyez un email à thamyikfoong(at)craftos.net.

## 🧾 Licence

Ce projet est sous [licence MIT](LICENSE). Vous êtes libre d'utiliser, d'héberger et de monétiser ce projet (vous devez créditer ce projet en cas de distribution et de monétisation).

---

## ⭐ Remerciements

Développé et maintenu par [CraftOS](https://craftos.net/) et les contributeurs [@zfoong](https://github.com/zfoong) et [@ahmad-ajmal](https://github.com/ahmad-ajmal).
Si **CraftBot** vous est utile, mettez une ⭐ au dépôt et partagez-le avec d'autres !

---

## Star History

<a href="https://www.star-history.com/?repos=CraftOS-dev%2FCraftBot&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
 </picture>
</a>
