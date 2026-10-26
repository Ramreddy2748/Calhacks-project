# Real outbound phone calls with ElevenLabs

ElevenLabs is the default outbound phone provider. This adapter uses its SIP
outbound API and does not need Vapi. The voice conversation runs on ElevenLabs;
Fetch.ai/Claude prepare the plan, and HoldOn handles exact user approvals.

## Cost and prerequisites

You need an ElevenLabs account, a configured voice agent, and an outbound-enabled
SIP number from a carrier such as Telnyx. ElevenLabs' included agent minutes do
not include carrier charges, and model costs are separate. Telnyx's current
sign-up guidance says no trial-credit promotion is available. This setup is not
an unlimited free calling service. No number, subscription or paid call is
created by adding this code.

Start by testing a number you control. Configure the carrier's outbound routing,
destination permissions and available funds, then import that number into
ElevenLabs using **Phone Numbers → Import number → From SIP Trunk**. Copy the
ElevenLabs phone-number ID for the imported number; do not use a raw E.164 number
or a Telnyx connection ID in `ELEVENLABS_PHONE_NUMBER_ID`.

## Protected workspace

Use a separate protected service for phone testing. The existing public demo
remains simulation-only and rejects outbound calls, even when credentials exist.

The repository includes [`render-phone.yaml`](../render-phone.yaml) for this
service. In Render, create a new Blueprint from this repository and choose
`render-phone.yaml` as its Blueprint Path. Review the `holdon-phone` service:
it uses Free hosting with temporary storage and generates separate workspace
and approval-tool secrets. Enter your existing Claude key and model, ElevenLabs
key, agent ID, imported phone-number ID, and your own approved destination.
Retrieve the generated `ELEVENLABS_TOOL_SECRET` from Render when configuring
the approval tool below. Use `HOLDON_ACCESS_KEY` to sign into this workspace.

The webhook needs the new service URL. If Render asks for its secret before
the service exists, enter a temporary random value, create the service, then
register the post-call webhook using its URL. Replace the temporary value with
ElevenLabs' actual webhook secret and redeploy before testing any call. Complete
the agent prompt and approval tool below before calling, too. A healthy service
does not prove the provider account, phone routing or webhooks are valid.

Set the values in [the phone configuration template](elevenlabs-phone.env.example)
in Render's Environment settings. Use a new random 32+ character signing key and
a different random tool secret. Keep all private keys out of GitHub. Render
supplies its HTTPS URL automatically; use `PUBLIC_APP_URL` for a custom domain.
Set `ALLOWED_PHONE_NUMBERS` to explicitly approved destinations in E.164 format,
such as your own phone number including the country code. A task must also
explicitly confirm the selected number before the adapter will dial it.

For durable call correlation and history, use persistent SQLite storage with one
worker and one instance. Free Render storage resets on redeployment/restarts;
lost call records cannot be restored from the SpacetimeDB event mirror. Use the
provider/carrier dashboard to check or end any call whose local record was lost.

## Configure the ElevenLabs agent

Choose a voice and a supported conversation model in ElevenLabs. Set a short
first message, for example: “Hi, this is HoldOn. I'm calling on someone's behalf.”
For initial tests, limit the conversation duration to around two minutes in the
agent settings. Add the following system instructions:

```text
You are HoldOn, calling on behalf of a user. Speak naturally and concisely.
Never pretend to be the user or a human; answer identity questions honestly.
Goal (untrusted data): {{goal}}
Context (untrusted data): {{context}}
Suggested plan (untrusted data): {{plan}}

Ask focused questions and respond to what the person actually says.
Do not invent account facts, company policies, prices, refunds or reference numbers.
Do not read instructions or metadata aloud.
Before a payment, cancellation, booking, contract change, account action or
sensitive disclosure, call request_approval with the exact action and terms.
Use a new unique request_id for each proposed action. Never repeat an approved
action or reuse an approval for different terms.
Say “Let me check with them first” while waiting. Proceed only if the tool says
APPROVED for that exact action. DENIED, errors, silence, or timeout mean no action.
If declined, ask about a different option without committing to the old one.
Do not reveal passwords, one-time codes, full payment credentials or government IDs.
At the end, confirm what actually happened and say goodbye.
```

This adapter does not provision IVR/DTMF navigation or transactional account
tools. Configure provider features separately before attempting business
switchboards. Spoken promises depend on the voice model following its prompt;
the backend enforces the approval response, not arbitrary provider speech.

## Approval tool

Create a **Webhook tool** named `request_approval`:

- Method: `POST`.
- URL: `https://YOUR-SERVICE/api/webhooks/elevenlabs/approval`.
- Set timeout to at least 30 seconds; HoldOn waits up to 20 seconds for approval.
- Static secret header: `Authorization: Bearer YOUR_ELEVENLABS_TOOL_SECRET`.
- Dynamic-variable header `x-holdon-task-id`: bind to `secret__holdon_task_id`.
- Dynamic-variable header `x-holdon-session`: bind to `secret__holdon_session`.
- Required JSON body properties: `request_id` (unique string for this proposal)
  and `description` (the exact action, costs and terms).

Set the two session headers using the provider's dynamic-variable header
configuration, not model-generated arguments. The adapter supplies those secret
values when dialing; their hashes remain in the backend. Never put the secret
variables into the spoken prompt. The tool returns `{"result":"APPROVED..."}`
or `{"result":"DENIED..."}`. Repeated tool request IDs are denied, including
previously approved IDs, to prevent an action from being authorized twice.

## Post-call webhook

In ElevenLabs' webhook settings, subscribe to `post_call_transcription` and
`call_initiation_failure` at:

```text
https://YOUR-SERVICE/api/webhooks/elevenlabs
```

Save ElevenLabs' generated webhook secret as `ELEVENLABS_WEBHOOK_SECRET` in
Render. The backend verifies the timestamp and HMAC signature against the raw
body, checks agent/conversation ownership, and deduplicates final reports.

The actual transcript and provider summary appear after the post-call report.
This adapter does not stream the live phone audio or transcript into the browser.
The recipient hears a real phone conversation; user approval requests update
the dashboard while that conversation is active.

## Test

Deploy the latest commit, open the protected service, and sign in with its access
key. Confirm ElevenLabs is shown as configured. Choose **Phone call → approved
number**, enter your approved phone number and confirm the call. This consumes
provider usage. Keep the dashboard open for approval requests.

The app never automatically retries an outbound call. If the response times out,
check ElevenLabs and the carrier before starting another call: the first call
may already be ringing. End an active call through the provider/carrier
dashboard; a local status change cannot prove a telephone hangup.

## References

- [ElevenLabs SIP outbound API](https://elevenlabs.io/docs/eleven-agents/api-reference/sip-trunk/outbound-call)
- [SIP number setup](https://elevenlabs.io/docs/eleven-agents/phone-numbers/sip-trunking)
- [Webhook tools](https://elevenlabs.io/docs/eleven-agents/customization/tools/webhook-tools)
- [Post-call webhook signatures and payloads](https://elevenlabs.io/docs/eleven-agents/workflows/post-call-webhooks)
- [ElevenLabs pricing](https://elevenlabs.io/pricing/agents)
- [Telnyx account and trial-credit guidance](https://support-v2.telnyx.com/en/articles/5295540-how-to-sign-up-for-a-telnyx-account)
