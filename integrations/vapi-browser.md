# Browser voice with Vapi

This connects your microphone to a real Vapi assistant. You act as the customer
representative while HoldOn pursues the task goal. It is a role-play, not a phone
call or an account transaction. No Twilio number, allowlisted destination, or
private Vapi API key is required. Vapi account access and available usage are
still required; browser calls are not free provider service. If the Vapi balance is zero and auto-reload is off, new calls are blocked. See [Vapi billing](https://docs.vapi.ai/billing/manage-billing-and-credits).

## Configure

1. Use Node **22.14 or newer**, as required by `@vapi-ai/web` 3.0.1. Install the
   updated frontend dependencies with `npm ci --legacy-peer-deps` in `frontend/`.
2. Create a Vapi assistant with your account's supported voice, transcriber, and
   model. Use the goal/context/plan prompt and synchronous `request_approval`
   function described in [the assistant setup](vapi-assistant.md). This app
   overrides the first message with an AI disclosure and browser role-play notice.
3. Set these in **backend/.env** (never paste private keys into frontend files):

   ```dotenv
   VAPI_PUBLIC_KEY=your-vapi-public-key
   VAPI_BROWSER_ASSISTANT_ID=your-browser-assistant-id
   VAPI_WEBHOOK_SECRET=your-long-random-webhook-secret
   ```

   `VAPI_ASSISTANT_ID` is used if no dedicated browser assistant ID is set.
   Neither `VAPI_API_KEY` nor `VAPI_PHONE_NUMBER_ID` is needed for this mode.
4. Give the assistant and its approval tool a publicly reachable **HTTPS** server
   URL ending in `/api/webhooks/vapi`. Configure its `x-vapi-secret` header to
   match `VAPI_WEBHOOK_SECRET`. Subscribe to `tool-calls` and `end-of-call-report`.
   Only expose this authenticated webhook through your reverse proxy/tunnel;
   the rest of this single-user API must remain local.
5. The approval tool must be server-based and synchronous, with required string
   argument `description`, and a timeout longer than 20 seconds (for example,
   30 seconds). Do not substitute a browser-only tool: Vapi's client-side tools
   cannot return a result to the model. On denial, timeout, or error, the assistant
   must leave the proposed action undone. It must not treat spoken consent as
   authorization; only the dashboard approval result authorizes that exact action.
6. Restart the backend and frontend using the commands in the [README](../README.md).
   The connection panel's "Configured" status checks settings only, not account
   validity, credits, webhook reachability, or assistant behavior.

## Try it

Click **Talk to HoldOn**, enter a goal, and choose **Prepare browser call**. Once
the plan is ready, press **Talk to HoldOn** in the call view and allow microphone
access. Localhost is supported; a hosted frontend must use HTTPS for microphone
access. The app asks for microphone permission before creating a provider call.

Speak as a representative: "I can offer a ten dollar discount with no contract
change. Would you like me to apply it?" The assistant should invoke the backend
tool and pause. Try both **Approve** and **Decline**. If the tool does not appear,
inspect the Vapi tool and server configuration rather than assuming authorization.

Use **Mute** to stop microphone input and **End session** to disconnect browser
audio. Leaving the call view also stops audio and releases microphone tracks.
Calls are not retried automatically. If a connection fails ambiguously, inspect
the Vapi dashboard before creating another session. A browser disconnect alone
does not prove provider-side hangup; the authenticated end report is authoritative.

Final SDK transcript messages are saved in order. Client partial captions are
temporary. Duplicate browser event IDs are ignored, late events cannot reopen a
finished task, and disconnect expires pending approvals. Authenticated provider
end artifacts replace incomplete client transcripts when available. Claude can
summarize the saved conversation when configured; otherwise the report includes
message count and the last representative reply without inventing an outcome.

The SDK receives only the Vapi public key and assistant ID. Private keys and the
webhook secret remain on the backend/provider configuration. A temporary browser
session token correlates the call with its task; it never authorizes commitments.
This remains a local, single-user development app, not an authenticated public
service. The Vapi assistant handles live replies; Fetch.ai routes planning,
approval checks, and reporting. Voice prompts do not guarantee arbitrary model
speech, and no transactional tools are provided.

## Verification

Automated tests use a fake SDK and test credentials, never a real microphone or
paid call. They cover permission denial, event ordering, stop/start races,
transcript persistence, approval routing, and reporting. A real audio conversation
and real webhook delivery still need to be verified with your Vapi account.

References: [Vapi web quickstart](https://docs.vapi.ai/quickstart/web),
[Web SDK](https://github.com/VapiAI/client-sdk-web),
[client-side tool limitations](https://docs.vapi.ai/tools/client-side-websdk),
[server events](https://docs.vapi.ai/server-url/events).
