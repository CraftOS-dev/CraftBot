<div align="center">
    <img src="assets/README_cover.png" alt="CraftBot" width="1280"/>
</div>

La plupart des harnais d'agents s'arrêtent au chat et aux appels d'outils. CraftBot va plus loin : il construit, fait évoluer et opère ses propres outils SaaS, puis se sert de cette couche d'outils pour communiquer avec vous et automatiser vos tâches.

Au-delà de cela, CraftBot dispose de toutes les capacités essentielles d'un harnais d'agent généraliste. Il exécute des tâches comme le ferait un employé à distance, retient vos préférences et vos objectifs, et vous aide de manière proactive à planifier et à agir sur ce qui compte vraiment pour vous.

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
  <a href="README.md">English</a> | <a href="README.ja.md">日本語</a> | <a href="README.cn.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ko.md">한국어</a> | <a href="README.es.md">Español</a> | <a href="README.pt-BR.md">Português</a> | <a href="README.de.md">Deutsch</a>
</p>

## ✨ Fonctionnalités phares

En plus d'être un agent IA capable de créer et d'opérer ses propres outils SaaS, CraftBot embarque toutes les fonctionnalités de base d'un harnais d'agent, ce qui lui permet de fonctionner comme un agent IA généraliste qui vous accompagne au quotidien sur vos tâches, vos outils, votre mémoire et vos workflows.

- **Profils d'agent** Plus de 40 profils d'agent (agent CEO, agent finance, agent responsable marketing, ingénieur DevOps, agent producteur vidéo, et 37 autres) prêts à travailler pour vous. Trouvez les rôles souhaités dans **[CraftBot Agent Bundles](https://github.com/CraftOS-dev/craftbot-agent-bundles)** et importez-les en un clic.
- **Catalogue de playbooks** Vous ne savez pas comment automatiser avec un agent IA ? CraftBot propose 120 playbooks prêts à l'emploi (répartis sur 19 catégories). Ouvrez le sélecteur de playbooks depuis la barre supérieure, choisissez un playbook, et il commence à exécuter la tâche pour vous.
- **Living UI.** Construisez, importez ou faites évoluer des applications personnalisées qui vivent à l'intérieur de CraftBot. L'agent est en permanence au courant de l'état de l'UI et peut lire, écrire et agir directement sur ses données.
- **Multi-tâches et routage de sessions.** Vous tapez encore `/new` à la main ? CraftBot sait quand démarrer une nouvelle session et quand reprendre une tâche, en gardant la conversation et le contexte unifiés.
- **Auto-hébergé et BYOK.** Système de fournisseurs LLM flexible qui prend en charge OpenAI, Google Gemini, Anthropic Claude, OpenRouter et plus encore. Ou hébergez votre propre modèle, sans dépenser un seul token, avec Ollama.
- **Système de mémoire.** Un second cerveau construit à partir de vos échanges avec CraftBot. Approche hybride : RAG + graphe de connaissances + système de fichiers de l'agent. À minuit, CraftBot « rêve » et consolide les événements survenus dans la journée.
- **Agent proactif.** Il apprend vos préférences, vos habitudes et vos objectifs de vie. Puis il planifie et déclenche des tâches (avec votre accord, bien sûr) pour vous aider à progresser.
- **Intégration d'outils externes.** Connectez vos applications comme Google Workspace, Slack, Notion, Zoom, LinkedIn, Discord, Telegram et bien plus (et bien d'autres à venir !) avec la prise en charge d'OAuth ou votre propre clé. Vous pouvez connecter plusieurs comptes à chaque intégration.
- **Skills et MCP.** Plus de 150 MCP et 170 Skills disponibles. Installation rapide de nouveaux Skills et MCP. Créez ou améliorez des Skills à partir de tâches terminées en un clic.
- **Interface web et CLI.** Utilisez CraftBot comme il vous convient le mieux : via une UI navigateur simple pour un usage quotidien, ou via la CLI pour le scripting et les environnements headless.

---


## 🧰 Pour commencer

Prérequis : Python 3.10+ · Node.js 18+ pour le mode navigateur

```bash
# 1. Cloner le dépôt
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. Installer, enregistrer le démarrage automatique et lancer CraftBot
python craftbot.py install
```

C'est tout. Le terminal se ferme tout seul, CraftBot tourne en arrière-plan et le navigateur s'ouvre automatiquement. Un **raccourci de bureau** est créé pour vous permettre de rouvrir le navigateur quand vous voulez.

**Gérer le service après l'installation :**

```bash
python craftbot.py start      # Démarre CraftBot en arrière-plan
python craftbot.py stop       # Arrête CraftBot
python craftbot.py restart    # Redémarre CraftBot
python craftbot.py status     # Vérifie s'il tourne et si le démarrage auto est activé
python craftbot.py logs       # Affiche la sortie récente des logs
python craftbot.py uninstall  # Arrête, supprime le démarrage auto et désinstalle les paquets
```

> [!TIP]
> Après `install` ou `start`, un **raccourci CraftBot sur le bureau** est créé automatiquement. Si vous fermez le navigateur, il suffit de double-cliquer sur le raccourci pour le rouvrir.

---

## 🌱 Living UI

**Living UI est un système/une application/un tableau de bord qui évolue avec vos besoins.**

<div align="center">
    <img src="assets/living_ui_banner.gif" alt="CraftBot Banner" width="1280"/>
</div>

- Besoin d'un tableau kanban avec un copilote IA intégré ?
- D'un CRM sur mesure, conçu exactement à la forme de votre workflow ?
- D'un tableau de bord d'entreprise que CraftBot puisse lire et piloter pour vous ?

Lancez-le comme une Living UI : elle tourne aux côtés de CraftBot et grandit au rythme de vos besoins.

### Trois façons de créer une Living UI

1. **Construire de zéro.** Décrivez ce que vous voulez en langage naturel. CraftBot
   échafaude le modèle de données, l'API back-end et l'UI React, puis itère avec
   vous à travers un processus de conception structuré.

<div align="center">
    <img src="assets/living-ui-custom-build.png" alt="Building a Living UI from scratch" width="448"/>
</div>

2. **Installer depuis le marketplace.** Parcourez les Living UIs créées par la communauté sur [living-ui-marketplace](https://github.com/CraftOS-dev/living-ui-marketplace).

<div align="center">
    <img src="assets/living-ui-marketplace.png" alt="Living UI marketplace" width="448"/>
</div>

3. **Importer un projet existant.** Pointez CraftBot vers un projet en Go, Node.js, Python,
   Rust, du code source statique ou un dépôt GitHub. Il détecte le runtime, configure les health checks et l'enveloppe dans une Living UI.

<div align="center">
    <img src="assets/living-ui-import.png" alt="Importing an existing project as a Living UI" width="448"/>
</div>

### Continue d'évoluer avec CraftBot dans la boucle

Une Living UI n'est jamais « finie ». Demandez à l'agent d'ajouter des fonctionnalités,
de redessiner une vue ou de la brancher à de nouvelles données au fur et à mesure que vos besoins évoluent.

CraftBot est intégré à chaque Living UI et **conscient de son état** :
il peut lire le DOM courant et les valeurs des formulaires, interroger les données de l'app via
l'API REST et déclencher des actions en votre nom.

### Garde les outils SaaS ouverts et vivants

Construisez, personnalisez et faites évoluer votre propre Living UI, et dépendez moins des outils par abonnement qui n'ont jamais été pensés pour coller parfaitement à vos besoins.

---
 
# Trois Living UIs à essayer en 5 minutes
 
- **📋 Tableau Kanban** : toutes les tâches, suivis et CTA au même endroit. CraftBot peut s'en charger et faire le travail de PM pour vous.
- **📊 Habit Tracker** : mettez en place et suivez vos habitudes. Un calendrier d'activité façon GitHub pour suivre vos habitudes comme on suit ses commits.
- **🐦 Luolinglo** : ce n'est pas Duolingo, mais vous pouvez y apprendre de nouvelles langues, créer des flashcards et vous entraîner avec CraftBot.

**[Parcourez le marketplace de Living UI et contribuez-y →](https://craftos.net/marketplace)**

---

## 🔧 Dépannage et problèmes courants

### Node.js manquant (pour le mode navigateur)
Si vous voyez **« npm not found in PATH »** en lançant `python run.py` :
1. Téléchargez la version LTS depuis [nodejs.org](https://nodejs.org/)
2. Installez-la et redémarrez votre terminal
3. Relancez `python run.py`

**Alternative :** Utilisez le mode CLI (Node.js non requis) :
```bash
python run.py --cli
```

### L'installation échoue à cause des dépendances
L'installateur affiche désormais des messages d'erreur détaillés avec des pistes de résolution. Si l'installation échoue :
- **Vérifiez votre version de Python :** assurez-vous d'avoir Python 3.10+ (`python --version`)
- **Vérifiez votre connexion internet :** les dépendances sont téléchargées pendant l'installation
- **Videz le cache de pip :** lancez `pip install --upgrade pip` et réessayez

### Problèmes d'installation de Playwright
L'installation de Chromium pour Playwright est optionnelle. Si elle échoue :
- L'agent **continue de fonctionner** pour les autres tâches
- Vous pouvez la sauter et l'installer plus tard via `playwright install chromium`
- Elle n'est nécessaire que pour l'intégration WhatsApp Web

Pour un dépannage plus approfondi, voir [INSTALLATION_FIX.md](INSTALLATION_FIX.md).

---
## 🐳 Lancer dans un conteneur

La racine du dépôt contient une configuration Docker avec Python 3.10, les paquets système essentiels (dont Tesseract pour l'OCR) et toutes les dépendances Python définies dans `environment.yml`/`requirements.txt`, afin que l'agent tourne de manière cohérente dans des environnements isolés.

Voici les étapes pour lancer notre agent dans un conteneur.

### Construire l'image

Depuis la racine du dépôt :

```bash
docker build -t craftbot .
```

### Lancer le conteneur

Par défaut, l'image lance l'agent avec `python -m app.main`. Pour le lancer de manière interactive :

```bash
docker run --rm -it craftbot
```

Si vous devez passer des variables d'environnement, utilisez un fichier env (par exemple basé sur `.env.example`) :

```bash
docker run --rm -it --env-file .env craftbot
```

Montez avec `-v` les répertoires qui doivent persister en dehors du conteneur (par exemple les dossiers de données ou de cache) et ajustez les ports ou les autres flags en fonction de votre déploiement. L'image embarque les dépendances système nécessaires à l'OCR (`tesseract`) et des clients HTTP courants, pour que l'agent puisse manipuler des fichiers et des APIs réseau directement dans le conteneur.

Par défaut, l'image utilise Python 3.10 et embarque les dépendances Python de `environment.yml`/`requirements.txt`, donc `python -m app.main` fonctionne directement.

---

## 🤝 Comment contribuer

Les PRs sont les bienvenus ! Le workflow (fork → branche depuis `dev` → PR) est détaillé dans [CONTRIBUTING.md](CONTRIBUTING.md). Toutes les pull requests passent automatiquement par une CI de lint + smoke test.

> [!IMPORTANT]
> **CraftBot** est en développement actif, avec des améliorations chaque semaine. Pour toute question ou un échange plus rapide, rejoignez-nous sur [Discord](https://discord.gg/ZN9YHc37HG) ou écrivez à thamyikfoong(at)craftos.net.

---

## 🧾 Licence

Ce projet est distribué sous [Licence MIT](LICENSE). Vous êtes libre de l'utiliser, de l'héberger et de le monétiser (en cas de distribution ou de monétisation, vous devez créditer ce projet).

---

## ⭐ Remerciements

Développé et maintenu par [CraftOS](https://craftos.net/) et ses contributeurs.  
Si **CraftBot** vous est utile, mettez une ⭐ au dépôt et partagez-le autour de vous !

---

## Historique des stars

<a href="https://star-history.dera.page/#CraftOS-dev/CraftBot&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
 </picture>
</a>
