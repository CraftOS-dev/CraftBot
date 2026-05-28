<div align="center">
    <img src="assets/living_ui_banner.gif" alt="CraftBot Banner" width="1280"/>
</div>

<div align="center">
    <img src="assets/craftbot_logo_text_small.png" alt="CraftBot" width="400"/>
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
  <a href="README.md">English</a> | <a href="README.ja.md">日本語</a> | <a href="README.cn.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ko.md">한국어</a> | <a href="README.es.md">Español</a> | <a href="README.pt-BR.md">Português</a> | <a href="README.de.md">Deutsch</a>
</p>

## ✨ Fonctionnalités phares

En plus d'être un agent IA capable de créer et d'opérer ses propres outils SaaS, CraftBot embarque toutes les fonctionnalités de base d'un harnais d'agent, ce qui lui permet de fonctionner comme un agent IA généraliste qui vous accompagne au quotidien sur vos tâches, vos outils, votre mémoire et vos workflows.

- **Living UI.** Construisez, importez ou faites évoluer des applications personnalisées qui vivent à l'intérieur de CraftBot. L'agent est en permanence au courant de l'état de l'UI et peut lire, écrire et agir directement sur ses données.
- **Multi-tâches et routage de sessions.** Vous tapez encore `/new` à la main ? CraftBot sait quand démarrer une nouvelle session et quand reprendre une tâche, en gardant la conversation et le contexte unifiés.
- **Auto-hébergé et BYOK.** Système de fournisseurs LLM flexible qui prend en charge OpenAI, Google Gemini, Anthropic Claude, OpenRouter et plus encore. Ou hébergez votre propre modèle, sans dépenser un seul token, avec Ollama.
- **Système de mémoire.** Une base de connaissance locale construite à partir de vos échanges avec CraftBot via RAG + système de fichiers de l'agent + distillation. À minuit, CraftBot « rêve » et consolide les événements survenus dans la journée.
- **Agent proactif.** Il apprend vos préférences, vos habitudes et vos objectifs de vie. Puis il planifie et déclenche des tâches (avec votre accord, bien sûr) pour vous aider à progresser.
- **Intégration d'outils externes.** Connectez-vous à Google Workspace, Slack, Notion, Zoom, LinkedIn, Discord et Telegram (et bien plus à venir !), avec identifiants embarqués et prise en charge d'OAuth.
- **Skills et MCP.** Plus de 150 MCP et 170 Skills disponibles. Installation rapide de nouveaux Skills et MCP. Créez ou améliorez des Skills à partir de tâches terminées en un clic.
- **Multi-plateforme.** Prise en charge complète de Windows, macOS et Linux, avec des variantes de code spécifiques à chaque plateforme et une conteneurisation Docker.
- **Interface web et CLI.** Utilisez CraftBot comme il vous convient le mieux : via une UI navigateur simple pour un usage quotidien, ou via la CLI pour le scripting et les environnements headless.

---

## 🧰 Premiers pas

Prérequis : Python 3.10+ · Node.js 18+ pour le mode navigateur

```bash
# 1. Cloner le dépôt
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. Installer, enregistrer le démarrage automatique et lancer CraftBot
python craftbot.py install
```

C'est tout. Le terminal se ferme tout seul, CraftBot tourne en arrière-plan et le navigateur s'ouvre automatiquement. Un **raccourci de bureau** est également créé pour vous permettre de rouvrir le navigateur quand vous voulez.

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

**La Living UI est un système / une app / un tableau de bord qui évolue avec vos besoins.**

- Besoin d'un tableau kanban avec un copilote IA intégré ?
- D'un CRM sur mesure, conçu exactement à la forme de votre workflow ?
- D'un tableau de bord d'entreprise que CraftBot puisse lire et piloter pour vous ?

Lancez-le sous forme de Living UI qui tourne aux côtés de CraftBot et grandit au rythme de vos besoins.

<div align="center">
    <img src="assets/living-ui-example.png" alt="Living UI example" width="1280"/>
</div>

### Trois façons de créer une Living UI

1. **Construire de zéro.** Décrivez ce que vous voulez en langage naturel. CraftBot
   échafaude le modèle de données, l'API back-end et l'UI React, puis itère avec vous
   à travers un processus de conception structuré.

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

Nous cherchons activement des développeurs qui souhaitent mettre en avant leurs Living UIs et les exporter vers le **[marketplace de Living UI](https://craftos.net/marketplace)**. Les PRs sont les bienvenus !

---
 
# Trois Living UIs à essayer en 5 minutes
 
- **📋 Tableau Kanban** — Toutes les tâches, suivis et CTA au même endroit. CraftBot peut s'en charger et faire le travail de PM pour vous.
- **📊 Habit Tracker** — Mettez en place et suivez vos habitudes. Un calendrier d'activité façon GitHub pour suivre vos habitudes comme on suit ses commits.
- **🐦 Luolinglo** — Ce n'est pas Duolingo, mais vous pouvez y apprendre de nouvelles langues, créer des flashcards et vous entraîner avec CraftBot.

**[Explorer le marketplace de Living UI et y contribuer →](https://craftos.net/marketplace)**

---
 
# CraftBot face aux alternatives
 
|                                  | v0 / Lovable / Bolt | OpenClaw | Claude Code | **CraftBot**                            |
| -------------------------------- | ------------------- | -------------------- | -------------------- | --------------------------------------- |
| **Construit des apps sur mesure**           | ✅ One-shot         | 🚫                   | ✅ (manuel)          | ✅ Conversationnel                       |
| **L'agent pilote l'app**       | 🚫                  | ⚠️ Via appels d'outils      | 🚫                   | ✅ Embarqué dans chaque Living UI         |
| **Mémoire d'agent persistante**      | 🚫                  | ✅            | ✅                   | ✅ RAG + système de fichiers d'agent + distillation        |
| **Auto-hébergeable**     | ⚠️ Partiel         | ✅                   | 🚫 SaaS              | ✅ MIT, sur votre machine                    |
| **Indépendant du modèle**     | ✅         | ✅                   | ⚠️ Partiel              | ✅ Principaux fournisseurs + OpenRouter                    |
 
---

## 🔧 Dépannage et problèmes courants

### Node.js manquant (pour le mode navigateur)
Si vous voyez **« npm not found in PATH »** en lançant `python run.py` :
1. Téléchargez la version LTS depuis [nodejs.org](https://nodejs.org/)
2. Installez-la et redémarrez votre terminal
3. Relancez `python run.py`

**Alternative :** utilisez le mode TUI, qui ne nécessite pas Node.js :
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

<a href="https://www.star-history.com/?repos=CraftOS-dev%2FCraftBot&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
 </picture>
</a>
