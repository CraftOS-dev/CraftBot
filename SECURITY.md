# Security Policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub: open the repository's **Security** tab and choose **Report a vulnerability**. Do not open a public issue, pull request or discussion for a vulnerability before it is fixed.

Include what you found, the affected version, and steps to reproduce. A harmless proof (for example, one that only creates a marker file) is the most useful.

We will acknowledge your report, keep you updated while we work on it, and publish a GitHub Security Advisory once it is fixed, crediting you unless you ask us not to.

## Supported versions

Security fixes go into the latest release. Please upgrade to it before reporting.

| Version | Supported |
| --- | --- |
| Latest release (1.4.x) | Yes |
| Older releases | No |

## Trust model

CraftBot is a personal agent that runs on your computer with your user account's permissions. It is built for one trusted owner per installation.

- **The agent can do what you can do.** It runs commands, reads and writes files, and uses the accounts you connect. The operating system user account is the boundary; CraftBot does not sandbox the commands the agent runs.
- **Outside content is untrusted.** Web pages, emails, chat messages from other people, files and MCP tool results can contain instructions aimed at the agent (prompt injection). Settings > Security lets you reduce what such instructions can achieve; see [the security levels guide](docs/security-levels.md).
- **The local interface is for this computer.** It listens on localhost and has no login of its own. Do not expose its ports to a network without putting an authenticating proxy in front of it.
- **Extensions run with full permissions.** MCP servers, skills, Agent Apps and profile bundles you install run code as you. Install only what you trust.

## In scope

- Ways for a website, an email, a third party's message, an MCP server, a skill or a profile bundle to run code, read secrets or act as the owner without the owner's approval when a security setting says it should not.
- Bypasses of a Settings > Security protection that its description says it provides.
- Exposure of credentials or of the local interface to other users or other machines.
- Vulnerabilities in the installer, updater or release artifacts.

## Out of scope

- Prompt injection that only makes the agent use permissions the owner gave it, at a security level that does not restrict them (for example Standard with Auto mode on).
- Anything that needs the attacker to already run code as the owner's user account.
- Commands the agent runs reaching files or the network: the file and network guards cover the agent's file and web tools, not the shell. Turn Auto mode off to approve commands before they run.
- Malicious MCP servers, skills or Agent Apps that the owner chose to install.
- Exposing the interface to the internet against the guidance above.
