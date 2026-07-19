# Service mode

Service mode runs CraftBot as a background process that starts when you log in, survives closing the terminal and the browser tab, and keeps everything time-based alive: [scheduled tasks](../core/concepts/scheduling.md), [proactive mode](../core/modes/proactive.md), and integration listeners that watch your Telegram, Slack, or email. If you want an assistant rather than a program you launch, this is the way to run it.

The service manager is `craftbot.py` in the repository root. Underneath, it's the same agent as `python run.py`. `craftbot.py` adds lifecycle management: dependency install, auto-start registration, a detached background process, readiness detection, and a desktop shortcut.

## Install and manage

```bash
python craftbot.py install
```

`install` does five things in order: installs dependencies → registers auto-start for your user account → starts CraftBot detached from the terminal → waits until the agent logs its ready marker, then opens the browser at `http://localhost:7925` → creates a desktop shortcut and closes the terminal.

After that, one command each for the whole lifecycle:

| Command | What it does |
|---|---|
| `python craftbot.py start` | Start in the background. If already running, restarts. Terminal closes itself when the agent is ready. |
| `python craftbot.py stop` | Stop the background process. |
| `python craftbot.py restart` | Stop, then start. |
| `python craftbot.py status` | Two answers: is CraftBot running right now, and is auto-start registered. |
| `python craftbot.py logs` | Recent service log output. `-n 200` for more lines. |
| `python craftbot.py install` | Full setup (see above). Safe to re-run. |
| `python craftbot.py uninstall` | Stop, remove auto-start registration, uninstall the pip packages, purge pip cache. Your data stays in the repo folder. |
| `python craftbot.py repair` | Re-fetch and reinstall the agent payload (packaged builds). |

Launch options pass through to the underlying launcher. Useful ones:

```bash
python craftbot.py start --frontend-port 8925 --backend-port 8926   # different ports
python craftbot.py start --cli                                      # service runs the CLI agent instead of browser mode
python craftbot.py install --no-conda                               # don't use the conda environment
```

The service always starts with `--no-open-browser` internally, so it never pops a browser on login. You open the UI when you want it via the shortcut or `http://localhost:7925`.

## What actually gets registered

Everything is per-user: no admin rights, no system-wide daemon. Two users on one machine can each run their own CraftBot with separate config and credentials.

=== "Windows"

    A **Task Scheduler** entry named `CraftBot`, triggered at your logon. If Task Scheduler registration fails (some managed machines restrict it), CraftBot falls back to an entry under the registry Run key (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`).

    Inspect or remove it manually if needed:

    ```powershell
    schtasks /Query /TN CraftBot /V /FO LIST    # inspect
    schtasks /Delete /TN CraftBot /F            # manual removal (uninstall normally does this)
    ```

=== "Linux"

    A **systemd user service** named `craftbot.service`. It starts at *login*, not boot, and runs entirely under your account.

    ```bash
    systemctl --user status craftbot     # inspect
    systemctl --user restart craftbot    # restart via systemd (equivalent to craftbot.py restart)
    ```

    !!! warning "Environment variables under systemd"
        A systemd user service does not inherit your shell's environment. If you set provider keys as shell `export`s, the service won't see them. Put keys in the settings UI (stored in `settings.json`) instead, or add `Environment=` lines to the unit file.

=== "macOS"

    A **launchd** agent, `com.craftbot.agent.plist`, loaded for your user session.

    ```bash
    launchctl list | grep craftbot       # inspect
    ```

## State files and logs

The service keeps its runtime state in a per-user data directory:

| Platform | Directory |
|---|---|
| Windows | `%LOCALAPPDATA%\CraftBot` |
| macOS | `~/Library/Application Support/CraftBot` |
| Linux | `$XDG_DATA_HOME/craftbot` (default `~/.local/share/craftbot`) |

Inside it:

| File | Purpose |
|---|---|
| `craftbot.pid` | PID of the running background process — how `status`/`stop` find it |
| `craftbot.log` | The service's own output. `craftbot.py logs` reads this. Startup is confirmed by the `CRAFTBOT IS READY` marker here. |
| `install.json` | What the installer set up (used by `status`, `repair`, `uninstall`) |

The **agent's** logs are separate and richer: each run writes a folder under `logs/` in the repository (`main.log` for the main agent, `all.log` for everything including sub-agents), rotated at 50 MB and kept 14 days. When you're debugging agent behavior, read those. When you're debugging "why didn't it start", read `craftbot.log`. See [Logs](../core/concepts/logs.md).

## Common setups

**Personal workstation (default).** `python craftbot.py install` once. CraftBot is there on every login. You open the browser UI when you need it, and proactive/scheduled work runs quietly the rest of the time.

**Always-on home server.** Install on a machine that never sleeps (home server, Raspberry Pi, small VPS) so schedules fire even with your laptop closed. The UI binds to localhost, so reach it by SSH port-forward or a private network like Tailscale:

```bash
ssh -N -L 7925:localhost:7925 you@server    # then open http://localhost:7925 locally
```

**Headless / CLI service.** `python craftbot.py start --cli` if the machine will never serve the browser UI. You interact through connected [integrations](../integrations/index.md) (Telegram, Slack, ...) instead.

## Security notes

- The UI binds to **localhost**, so nothing is reachable from other machines unless you tunnel or proxy.
- There is **no built-in authentication** on the browser UI: anyone who can reach the port controls your agent. Do not expose the port directly to the internet. If you need remote access, use SSH forwarding or a VPN. If you truly must go public, put an authenticating reverse proxy in front.
- API keys and integration credentials stay in local files (`settings.json`, `.credentials/`) with owner-only permissions where the OS supports it. See [Credentials](../integrations/credentials.md).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Nothing starts after login | Auto-start entry missing or disabled | `python craftbot.py status`; re-run `install`. Windows: check `schtasks /Query /TN CraftBot`; Linux: `systemctl --user status craftbot` |
| `status` says running but UI won't load | Frontend build failed or port conflict | `python craftbot.py logs`; try `restart`; check nothing else owns `7925`/`7926` |
| Worked in foreground, fails as a service | Environment difference — usually keys set as shell env vars | Move keys into the settings UI / `settings.json` (see the systemd warning above) |
| Scheduled/proactive tasks don't fire | Service not running, or proactive disabled | `craftbot.py status`, then check `proactive.enabled` in [settings](../core/configuration/config-json.md) |
| Stale PID / won't stop | Process died without cleanup | Delete `craftbot.pid` in the state directory, then `start` again |
| Desktop shortcut opens a blank page | Agent stopped | `python craftbot.py start`, wait for ready, reload |

More: [Runtime issues](../reference/troubleshooting/runtime.md).

## Next

- [Scheduling](../core/concepts/scheduling.md): the recurring work that makes always-on worthwhile
- [Proactive mode](../core/modes/proactive.md): let the agent propose its own tasks
- [Integrations](../integrations/index.md): talk to your always-on agent from Telegram, Slack, and everywhere else
