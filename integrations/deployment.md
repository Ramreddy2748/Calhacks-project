# Deploy the private HoldOn workspace

The Docker image builds the dashboard with Node 22.14 and runs FastAPI on Python
3.12 as a non-root user. It serves the dashboard and API from one origin so
microphone permissions, secure session cookies, and SSE work together. It uses
one API worker and a persistent SQLite volume at `/data`.

## Provider selection

Annapurna Labs/AWS is a confirmed Cal Hacks 13.0 sponsor according to
[SpacetimeDB's event announcement](https://spacetimedb.com/blog/spacetime-at-calhacks).
No event hosting-credit offer was verified. Ask the AWS desk about credits and
account access before provisioning paid resources. The image can run on an AWS
Linux VM with persistent storage, or another Docker host with HTTPS and a disk.
This project does not create cloud resources or assume those services are free.

An ephemeral/free container without persistent storage is unsuitable for the
current SQLite state and replication checkpoint. Multiple replicas/workers are
also unsupported. No public deployment has been created yet.

## Configuration

Set `backend/.env` using `.env.example` as a guide. For hosting, supply:

```dotenv
HOLDON_REQUIRE_AUTH=1
HOLDON_ACCESS_KEY=a-random-secret-of-at-least-32-characters
PUBLIC_APP_URL=https://your-holdon-host
DATABASE_PATH=/data/holdon.sqlite3
```

Generate a new secret locally; do not use the example string. Missing/short keys
or a non-HTTPS public origin cause hosted mode to fail at startup. The access key
is exchanged for a signed, HTTP-only, Secure, SameSite=Strict session cookie that
expires after 12 hours. Rotating the key invalidates existing sessions. The gate
protects task APIs, browser call configuration, approval decisions, and SSE.

This is a single-workspace access key, not a multi-user account system. Keep HTTPS
enabled and restrict access to the people sharing that workspace.

## Build and run

From the repository root:

```sh
docker build -t holdon .
docker compose config --quiet
docker compose up --build -d
```

Compose overrides the local example's auth flag to enable hosted protection and
binds the application to loopback port 8000. Put an HTTPS reverse proxy in front
of it, using the same hostname as `PUBLIC_APP_URL`. Preserve cookies and streaming
responses, disable buffering of `/api/tasks/*/events`, and allow long-lived SSE
connections. Mount `/data` on persistent storage and back it up.

The image also runs directly on a Docker host. If passing an env file, explicitly
set `HOLDON_REQUIRE_AUTH=1`; never carry the local-only `0` flag into a public app.
The app listens on port 8000 inside the container.

Provider callbacks use `/api/webhooks/vapi`. This route bypasses the workspace
cookie but still requires `x-vapi-secret`. Anonymous health checks reveal only
whether login is required. The frontend bundle contains no provider private keys.

The optional public ACP agent runs separately; route its `/submit` to port 8001,
not the private API. See [Agentverse setup](agentverse.md). Provider credentials,
DNS/TLS configuration, public routing, and a hosting account are still required
to activate external integrations.

## Verify after deploying

Check that signed-out users cannot list calls, sign in through HTTPS, create a
demo, approve/decline it, and receive a summary. Then test the Vapi browser setup
and authenticated webhook from your account. Confirm persistence after a restart
and check the SpacetimeDB queue. SMS and phone calls remain optional and require
their own provider credits. A Docker build alone is not a public deployment.
