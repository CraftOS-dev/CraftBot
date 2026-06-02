# CraftBot multi-tenant OAuth broker

One shared OAuth callback for **all** per-user containers, so you register a
single redirect URI with Google (and any other provider) no matter how many
users you have.

```
                    craft-dev.com  (HTTPS reverse proxy)
            /oauth/callback ─────────────► oauth-broker (this service)
                                                  │ reads tenant from `state`
                                                  ▼  302
   user1.craft-dev.com ──► container (User 1)  ◄──┘
   user2.craft-dev.com ──► container (User 2)
```

## How it works

1. A user on `user1.craft-dev.com` clicks **Connect**.
2. Their container builds the provider sign-in URL with
   `redirect_uri = https://craft-dev.com/oauth/callback` and
   `state = "user1.<random>"`.
3. The user signs in; the provider redirects to the **apex** callback, which the
   proxy sends to **this broker**.
4. The broker reads `user1` from `state` and 302-redirects the browser to
   `https://user1.craft-dev.com/oauth/callback?...` (same query preserved).
5. The container matches `state`, exchanges the code for tokens, done.

No database. The `state` value is the routing ticket.

## 1. Configure each CraftBot container

Set two env vars per container (the rest of CraftBot is unchanged):

```bash
CRAFTBOT_TENANT_ID=user1                               # this container's subdomain label
CRAFTBOT_OAUTH_BROKER_URL=https://craft-dev.com/oauth/callback   # same on every container
```

- `CRAFTBOT_TENANT_ID` **must** equal the subdomain label and must not contain a dot.
- Leave both **unset** for desktop / single-container installs — behavior is unchanged
  (the redirect falls back to the browser's own origin).

## 2. Run the broker on the host

```bash
BROKER_BASE_DOMAIN=craft-dev.com python deploy/oauth_broker/broker.py
# listens on 0.0.0.0:8788, GET /oauth/callback
```

Or with Docker (see `Dockerfile`):

```bash
docker build -t craftbot-oauth-broker deploy/oauth_broker
docker run -d --name oauth-broker -p 8788:8788 \
  -e BROKER_BASE_DOMAIN=craft-dev.com craftbot-oauth-broker
```

Env vars: `BROKER_BASE_DOMAIN` (required), `BROKER_PORT` (8788), `BROKER_HOST`
(0.0.0.0), `BROKER_CALLBACK_PATH` (/oauth/callback), `BROKER_SCHEME` (https).

## 3. Wire the reverse proxy

The apex `craft-dev.com/oauth/callback` must reach the broker; subdomains keep
going to their containers as they already do.

### nginx

```nginx
# Apex: /oauth/callback -> broker
server {
    listen 443 ssl;
    server_name craft-dev.com;          # apex only, NOT *.craft-dev.com
    # ... ssl_certificate etc. ...

    location /oauth/callback {
        proxy_pass http://127.0.0.1:8788;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# Subdomains keep routing to each user's container (your existing config).
server {
    listen 443 ssl;
    server_name ~^(?<tenant>[a-z0-9-]+)\.craft-dev\.com$;
    # ... route to the container for $tenant, including /oauth/callback ...
}
```

### Caddy

```caddy
craft-dev.com {
    handle /oauth/callback {
        reverse_proxy 127.0.0.1:8788
    }
    # ... your other apex routes ...
}

*.craft-dev.com {
    # existing per-tenant routing to containers (handles /oauth/callback too)
    reverse_proxy { to {your container upstream} }
}
```

## 4. Register with Google (once, ever)

Google Cloud Console → **APIs & Services → Credentials** → your OAuth client
(type must be **Web application**) → **Authorized redirect URIs** → add exactly:

```
https://craft-dev.com/oauth/callback
```

That's the only redirect URI you ever register — adding new users needs no
Console changes. Repeat the equivalent step for any other OAuth provider
(GitHub, Notion, etc.): register the same single apex callback URL.

## Security notes

- The broker only ever redirects to `<tenant>.<base_domain><callback_path>`, and
  `tenant` is validated against a strict DNS-label regex — a crafted `state`
  can't inject a different host, scheme, port, or path.
- A forged `state` like `victim.<attacker-random>` is harmless: the victim's
  container has no matching pending flow, so it drops the code without acting.
- For defense-in-depth you can additionally sign `state` (HMAC) in the container
  and verify it in the broker; not required for correctness.
