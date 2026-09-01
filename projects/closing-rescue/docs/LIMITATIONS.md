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
- The first local slice is not deployed. A public URL and social post follow only after `make smoke-solari` passes with a real key.
