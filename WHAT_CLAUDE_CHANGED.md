# What Claude changed — plain summary

This file is just for you to read. Open it any time.

## The problem
Integrations (Gmail, LinkedIn, etc.) did not work inside the EC2 Docker
containers. They worked on a local install but failed on the server with
"Access blocked: redirect_uri_mismatch".

## What I changed in the code (already saved + pushed to GitHub)

1. **craftos_integrations/oauth_flow.py**
   - Added a "tenant" tag into the OAuth login so the server knows which
     container the user came from.
   - Added a log line that prints the exact login URL (for easy debugging).

2. **app/ui_layer/adapters/browser_adapter.py**
   - The container now automatically sends the correct login address
     (`https://craft-dev.com/oauth/callback`) for every user — no manual setup.
   - Added a `/healthz` page so the dashboard knows when a container is ready
     (so "Open CraftBot" only works when it's actually up).

3. **New folder: deploy/oauth_broker/**
   - A small helper service ("broker") that catches the Google login and sends
     it back to the right user's container.

4. **New folder: deploy/egress_proxy/**
   - A network lock so containers can ONLY reach the integration websites and
     nothing else. This protects you from another AWS abuse warning.

## Status

- Writing the code:        DONE  (saved in git history, commit "Bug Fix")
- Google accepted login:   DONE  (your last screenshot showed code=4/0A...)
- Container running new code: DONE
- **Broker deployed on server:  NOT YET**  <-- this is why you see "404"
- **URL registered in Google:   you did this (it worked!)**

## The ONLY thing left

Start the broker on the server so `craft-dev.com/oauth/callback` stops showing
"404 page not found". This is a server command, NOT a code change — that's why
you won't see new changes in git for it.

The craft-dev.com Claude (which runs ON the server) must run:

    BROKER_BASE_DOMAIN=craft-dev.com python deploy/oauth_broker/broker.py

and point the website so `craft-dev.com/oauth/callback` goes to that broker.

After that, integrations work.
