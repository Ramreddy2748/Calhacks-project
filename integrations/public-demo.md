# Publish HoldOn as a public demo

The root `render.yaml` deploys the existing Docker image as one Free web service.
The dashboard and API share an HTTPS origin. A Render account is required; the
repository alone does not create a running website.

## Launch

1. Open https://render.com/deploy?repo=https://github.com/Ramreddy2748/Calhacks-project.
2. Create a Render account and connect GitHub if asked.
3. Review the Blueprint. It requests a **Free** web service, with no paid disk.
4. Deploy and wait for the service to become Live.
5. Open the actual HTTPS URL shown by Render and share that URL.

Render supplies `RENDER_EXTERNAL_URL`. The backend uses it to validate the public
origin. If you attach a custom domain, set `PUBLIC_APP_URL` to its HTTPS origin.
The Blueprint generates the signing key; never copy provider keys into GitHub.
Automatic redeploys are disabled. Deploy repository updates manually in Render.

## Startup configuration errors

If startup says "Hosted mode requires..." or "Private workspace mode requires...",
open Render → service → Environment and set `HOLDON_PUBLIC_DEMO=1`,
`HOLDON_REQUIRE_AUTH=0`, and `HOLDON_ACCESS_KEY` to a new random secret with at
least 32 characters. Generate it locally with
`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`.
These settings must be in Render, not only in your laptop's `.env` file.
Remove any `PUBLIC_APP_URL` pointing to localhost; Render supplies its HTTPS
origin automatically. Choose **Manual Deploy → Deploy latest commit** afterward.

## Enable Claude

Initially the demo runs without paid provider credentials. To enable AI plans,
conversations, and summaries, add these in Render → service → Environment:

```dotenv
ANTHROPIC_API_KEY=your_private_key
ANTHROPIC_MODEL=a_model_available_to_your_account
```

Save and redeploy. This uses your Anthropic account's paid usage. The app allows
20 simulation starts per UTC day across all visitors, three per signed visitor
session, one active simulation per visitor, and four active simulations total.
Each Claude simulation makes one planning request, up to three negotiation
requests, and one report request. Failed starts count toward the daily cap.
`PUBLIC_DEMO_DAILY_LIMIT` adjusts the shared limit. Cookie deletion can bypass
the per-session cap, but not the shared cap within the current database lifetime.
Use account-level provider spending controls for a financial spending limit.

Do not copy Vapi or Twilio credentials into this public demo. Real voice/phone
calls, SMS, and provider webhooks are disabled by public-demo mode.

## Privacy and limitations

- Visitors can list, view, stream, approve, and cancel only their own tasks.
- Sessions use signed, HttpOnly, Secure, SameSite=Strict cookies, expiring after
  12 hours. Clearing cookies loses access to previous history; there is no login
  recovery or cross-device account.
- Declining a proposal explores alternatives, up to three proposals. An approval
  expires after one minute of inactivity. End demo stops the session immediately.
- Only use fictional examples; do not enter passwords, payment details, or real
  private account information. The operator and optional model provider process
  submitted task content.
- Free Render instances sleep after inactivity and have an ephemeral filesystem.
  SQLite history, replication checkpoints, and usage counters can reset on
  restarts/redeploys. This tier is for a temporary demo, not durable personal data.
- For durable history and quotas, use a persistent disk on a paid plan. Keep a
  single instance and one API worker. The SpacetimeDB mirror is not a restore
  mechanism for SQLite, and is not configured by the public Blueprint.
- This is a limited public simulation, not a production multi-user phone service.

## Verify the live link

1. Open the link in a normal window and create a simulated task.
2. Open the same link in an incognito window. Its history must be empty.
3. Approve/decline from the first window; verify updates stay in that session.
4. Check that the UI labels the run as a simulation and offers no real calling.
5. If Claude is enabled, verify the plan and conversation reflect your goal.

References: [Render deployment button](https://render.com/docs/deploy-to-render),
[Free hosting limitations](https://render.com/docs/free),
[Blueprint specification](https://render.com/docs/blueprint-spec).
