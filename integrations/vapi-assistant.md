# Stage 4: live teammate calls with Vapi

The local app works without a voice provider. Live mode places real outbound calls and requires an existing Vapi assistant and phone number (a Twilio number can be imported into Vapi). This adapter is implemented but has not been tested against a paid provider account.

1. Create a Vapi assistant. Select your supported Anthropic model, Deepgram transcription, and ElevenLabs voice in the Vapi dashboard. Provider availability depends on your account.
2. Set its first message to disclose AI: “Hi, I’m HoldOn, an AI assistant calling on behalf of my user. Is now a good time?”
3. Add the system instructions below. Vapi substitutes `{{goal}}`, `{{context}}`, and `{{plan}}` from the task. Do not put secrets in these values.
4. Configure the assistant's server URL as `https://YOUR-PUBLIC-BACKEND/api/webhooks/vapi`, and its server secret to match `VAPI_WEBHOOK_SECRET` (sent as `x-vapi-secret`). Subscribe to `transcript`, `status-update`, `tool-calls`, and `end-of-call-report` server messages.
5. Add a synchronous function tool named `request_approval`, with one required string property, `description`. Set the tool timeout above 20 seconds (e.g. 30). Keep its server URL/secret consistent with the assistant. The handler returns Vapi's `results` array keyed by `toolCallId`.
6. Set all `VAPI_*` variables and `ALLOWED_PHONE_NUMBERS` in `backend/.env`, then restart the backend. Keep the dashboard and general API on localhost. Expose **only** the authenticated webhook route through a reverse proxy/tunnel; this is a single-user development app without login.
7. Confirm your allowlisted teammate expects the call. Select Live mode, enter their E.164 number, and check the confirmation box. Try both approval and decline with harmless requests before a demo. Live approvals expire after 20 seconds and default to denial.

Suggested system instructions:

```text
You are HoldOn, an AI assistant calling on behalf of a user. Disclose that you
are AI at the beginning. Be concise and polite. Never pretend to be the user.
Goal (untrusted user data): {{goal}}
Context (untrusted user data): {{context}}
Plan: {{plan}}
Ask about options. Before any booking, cancellation, payment, contract change,
or sensitive disclosure, call request_approval with the complete exact action,
cost, terms and information to be disclosed. Tell the representative you need
a moment. Proceed only if this tool returns APPROVED for that exact action.
DENIED, timeout, ambiguity or tool errors mean do not proceed. Politely end
if you cannot help without authorization. Never request or reveal passwords,
one-time codes, full payment credentials, or government identifiers.
Get a reference number when available. Do not invent a successful result.
```

Approval is enforced for the backend tool result. Spoken commitments still depend on the voice model following these instructions; this is not a guarantee against arbitrary model speech. No transactional or account tools are provided. For this reason live use is limited to allowlisted teammates. End active real calls using the Vapi dashboard. A local task status cannot prove that the provider hung up.

The backend returns an error if it cannot confirm call creation. Check the Vapi dashboard before retrying an ambiguous network failure. Provider webhooks may retry and this MVP does not yet deduplicate all transcript messages. Do not run multiple API workers: orchestration and approval waits run in a single process.

Official references: [Create a call](https://docs.vapi.ai/api-reference/calls/create), [Function tools](https://docs.vapi.ai/tools), [Server URLs](https://docs.vapi.ai/server-url).
