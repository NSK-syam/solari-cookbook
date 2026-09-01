# Known limitations

- Permit coverage is Delaware-only in the MVP, and record matching depends on parcel identifiers.
- Fixture addresses and evidence values are synthetic; they demonstrate workflow behavior rather than claims about real homes.
- Live public APIs can be unavailable, delayed, incomplete, or spatially coarse.
- NOAA station observations may have missing hourly precipitation values and are only an urgency modifier.
- The deterministic demo reasoner is used when no OpenAI API key is configured; model reasoning is optional and remains bound by the same policy gates.
- County requests and vendor orders are simulated. No external message, booking, or charge occurs.
- The application is not a licensed inspection, diagnosis, appraisal, title opinion, or credit decision.
- The MVP uses local SQLite and documents rather than automates its 30-day production retention target.
- Solari replay URLs are signed and may expire; the session ID remains in the receipt so a reviewer can reconcile it in the Solari console.
- The fixture application is deployed at [closing-rescue.vercel.app](https://closing-rescue.vercel.app). Its SQLite database lives in ephemeral `/tmp` storage, so it is a reviewer demo rather than a durable production deployment.
- Live Solari execution is disabled on the public deployment until persistent storage and a server-side key are configured. The committed proof pack contains sanitized receipts from a successful sandbox, recorded-browser, and approval-gated desktop walkthrough.
- No LinkedIn or X post has been published. Social publishing remains an explicit user-approved submission step.
