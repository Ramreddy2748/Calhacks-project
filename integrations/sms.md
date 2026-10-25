# Summary SMS

Summary texts are optional and **never sent automatically**. Once a task has a
summary, choose **Text summary**, review the body and masked destination, and
explicitly confirm before pressing **Send SMS**. Demo reports retain their
simulation disclosure. This uses Twilio messaging credits; no live SMS was sent
or verified during implementation.

Configure a messaging-capable sender and your own recipient in `backend/.env`:

```dotenv
TWILIO_ACCOUNT_SID=your-account-sid
TWILIO_AUTH_TOKEN=your-auth-token
TWILIO_SMS_FROM=your-twilio-number-in-e164-format
TWILIO_SMS_TO=your-own-number-in-e164-format
```

The destination is fixed by the backend configuration; API callers cannot choose
arbitrary recipients. Trial accounts may require a verified recipient. Sender
registration requirements and available messaging credits depend on your account.

An accepted/queued response is not delivery confirmation. **Check delivery** reads
the provider's current message status. Ambiguous timeouts are recorded as unknown
and cannot be retried from the app, preventing accidental duplicate charges.
Check Twilio manually in that case. Restart recovery similarly marks unfinished
send attempts as unknown. Explicit retries are permitted after a known failed
attempt; the confirmation box resets after every send.

Messages may be billed as multiple segments. No credits, sender, or recipient
has been provisioned by this project.

Reference: [Twilio Messages API](https://www.twilio.com/docs/messaging/api/message-resource).
