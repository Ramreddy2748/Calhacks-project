# Public Agentverse planner

The public entry point is a separate ACP agent, **HoldOn Public Planner**. It
returns a deterministic plan with an introduction and approval steps. It does not
read the private task store, place calls, expose transcripts, approve commitments,
or spend Claude/Vapi credits. The four operational roles remain private.

## Prepare

Create an Agentverse account and API key, and a stable secret seed of at least
32 characters. Set these in `backend/.env`:

```dotenv
AGENTVERSE_API_KEY=your-agentverse-key
AGENTVERSE_SEED=your-stable-secret-seed
AGENTVERSE_ENDPOINT=https://your-agent-host/submit
AGENTVERSE_PORT=8001
```

Run the agent as a separate process using the existing backend dependencies:

```sh
PYTHONPATH=backend .venv/bin/python -m app.public_agent
```

Alternatively, the optional Compose profile runs this process without passing it
the private API's provider credentials:

```sh
docker compose --env-file backend/.env --profile agentverse up --build -d
```

Reverse-proxy the public HTTPS `/submit` endpoint to this process on port 8001.
Keep the main application's call APIs behind workspace authentication. Do not
publish the private orchestration agents or disable their sender checks.

## Register

After the public endpoint is reachable, explicitly run:

```sh
PYTHONPATH=backend .venv/bin/python -m app.register_agent
```

This uses the installed official `register_chat_agent` helper to prove ownership,
publish the public planner profile, and request activation. The seed must match
the running process. Registration is not performed during backend startup, and
is not claimed successful without an affirmative provider response.

The process uses the Almanac API registration policy, rather than ledger-based
registration. Keep the endpoint running and verify the profile in your own
Agentverse account. Registration, public reachability, and ASI:One discovery have
not been verified without those account settings and a deployed endpoint.

References: [Agentverse onboarding](https://docs.agentverse.ai/documentation/launch-agents/agentverse-sdk/u-agents),
[official registration helper](https://github.com/fetchai/uAgents/blob/main/python/uagents-core/README.md).
