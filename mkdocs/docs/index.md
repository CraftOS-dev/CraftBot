
# CraftBot

CraftBot is a minimal yet powerful computer-use AI agent that can perform complex computer-based and browser-based tasks. It can autonomously interpret tasks, plan actions, and execute actions to achieve goals. Depending on the task, it can switch between CLI and GUI mode, and the codebase is designed to serve as a foundation for building your own agents.

## Why this project exists

CraftBot is aimed at teams and builders exploring:
- system-based agentic AI
- runtime code generation
- autonomous execution for real workflows

It is open-source and still in active development — suggestions, feedback, and contributions are welcome.

## What you can do with it

- Use the built-in agent to plan and execute multi-step tasks
- Subclass the base agent to build specialized behaviors or workflows
- Interact with the agent through a TUI (text-based interface)

## Key features

- **Single Base Agent Architecture** — a simple, extendable core for reasoning, planning, and execution
- **CLI/GUI mode** — the agent can switch between CLI and GUI depending on task complexity (GUI is experimental)
- **Subclass & Extend** — build your own agents by inheriting from the base class
- **Task Document Interface** — define structured tasks for in-context learning
- **Actions Library** — reusable tools (web search, code execution, I/O, etc.)
- **Lightweight & Cross-Platform** — works across Linux and Windows

## Project status

GUI mode is still experimental. You should expect issues if/when the agent switches to GUI mode.

## Roadmap

- Memory module (coming next)
- External tool integration (pending)
- MCP layer (pending)
- Proactive behaviour (pending)

## Docs

- Start here: [Getting started](getting-started.md)

## Community & contributing

This project welcomes suggestions and feedback.

- Read: `README.md` (project overview and key concepts)
- Read: `CONTRIBUTING.md` (contribution guidance)

At the moment, the project does not have checks set up for direct code contributions, but feedback and suggestions are appreciated. If you’d like to contribute, the easiest ways to help are:
- open an issue with a bug report or feature request
- share a minimal repro case for problems you hit
- propose design/architecture improvements
- help improve docs (clarity, examples, structure)

You can contact the maintainer at:
- GitHub: `@zfoong`
- Email: `thamyikfoong(at)craftos.net`

## License

This project is licensed under the MIT License. You are free to use, host, and monetize this project (credit is required for distribution/monetization).

## Acknowledgements

Developed and maintained by CraftOS and contributors `@zfoong` and `@ahmad-ajmal`.

If you find CraftBot useful, please star the repository and share it with others.
