# Egress allowlist proxy — keep integration traffic in, abuse traffic out

Integrations **must** reach their providers (Gmail → Google, Discord → Discord,
etc.) — there's no way around that. What you *can* do is make sure the container
can reach **only those providers and nothing else**. Then even if the container
is compromised again, it can't be used to scan or attack random hosts — which is
exactly the behavior that got the EC2 instance flagged by AWS.

```
  CraftBot container ──► egress-proxy ──► internet
   (no direct net)        allowlist        only allowed domains pass;
                          + ports 80/443   everything else DENIED
```

The block is enforced **outside** the app (Docker network + proxy), so a
compromised app process can't bypass it.

## Files

| File | What it is |
|------|-----------|
| `allowlist.txt` | The only domains allowed out (one regex per line). |
| `tinyproxy.conf` | Proxy config: deny-by-default, CONNECT only to 80/443. |
| `Dockerfile` | Builds the tiny Alpine + tinyproxy proxy image. |
| `docker-compose.yml` | Wires CraftBot onto an `internal` network with no direct internet; proxy is its only way out. |

## How the lockdown works

1. **`internal: true` network** — the CraftBot container is placed on a Docker
   network with no NAT, so it physically cannot reach the internet directly.
2. **Proxy is the only exit** — the proxy sits on both the internal network and
   an internet-connected one. CraftBot's `HTTPS_PROXY` points at it.
3. **Deny by default** — `FilterDefaultDeny Yes` means only hosts matching
   `allowlist.txt` are allowed; everything else is refused.
4. **Ports locked** — `ConnectPort 443/80` blocks HTTPS tunnels to other ports
   (SSH, mining pools, etc.).

Because CraftBot uses `httpx` with `trust_env=True`, setting `HTTPS_PROXY`/
`HTTP_PROXY` is all it takes — no code change needed.

## Run it

```bash
# 1. build + start
docker compose -f deploy/egress_proxy/docker-compose.yml up -d --build

# 2. set your CraftBot image + per-tenant CRAFTBOT_TENANT_ID in the compose file
```

## Test it (prove the lock works)

From **inside** the CraftBot container (or any container on the `egress` net):

```bash
# Allowed — should succeed:
curl -x http://egress-proxy:8888 https://api.github.com/zen

# Not on the list — should be REFUSED by the proxy:
curl -x http://egress-proxy:8888 https://example.com
curl -x http://egress-proxy:8888 https://1.2.3.4

# Direct (no proxy) — should fail/timeout, proving no direct internet:
curl --max-time 5 https://api.github.com/zen
```

The first works; the rest are blocked. That's the proof the container can reach
integrations and nothing else.

## The allowlist (what each entry is for)

| Pattern | Integrations |
|---------|--------------|
| `googleapis.com`, `accounts.google.com` | Gmail, Calendar, Docs, Drive, YouTube + Google OAuth |
| `github.com` | GitHub |
| `discord.com` | Discord |
| `slack.com` | Slack |
| `notion.com` | Notion |
| `asana.com` | Asana |
| `atlassian.com` | Jira |
| `microsoft.com`, `microsoftonline.com` | Outlook (Graph + login) |
| `facebook.com` | WhatsApp Business (Graph) |
| `line.me` | LINE |
| `larksuite.com`, `feishu.cn` | Lark |
| `telegram.org` | Telegram |
| `twitter.com`, `x.com` | Twitter/X |
| `linkedin.com` | LinkedIn |
| `patreon.com` | Patreon |
| `craft-dev.com` | your own OAuth broker |

## Adding a new integration later

Add its API domain to `allowlist.txt` and restart the proxy:

```bash
docker compose -f deploy/egress_proxy/docker-compose.yml restart egress-proxy
```

If an integration silently fails to connect, check the proxy logs — a denied
domain shows up there, and you just add it to the list.

## Note on WhatsApp Web / QR integrations

Some integrations (WhatsApp Web) use a real browser / WebSocket and many
rotating WhatsApp edge hosts that don't fit a tidy domain list. If you rely on
those, you'll need to widen the allowlist for that integration (or run it on a
separately-scoped container). The API-based integrations above are fully covered.
