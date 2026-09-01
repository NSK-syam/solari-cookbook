# Sanitized Solari proof pack

These artifacts are the durable, reviewable subset of a live Solari run performed on September 1, 2026. They contain no API key, cookie, browser endpoint, owner name, street address, or signed replay URL.

| Artifact | Product | What it proves | SHA-256 |
| --- | --- | --- | --- |
| `sandbox-manifest-bc4eed363440d4f5.json` | Solari Sandbox | A microVM processed all 47 loans, retained contradiction classifications, calculated preventable exposure, matched the submitted input hash, and exited successfully. | `bc4eed363440d4f5c598becae30cea65e385a2e3992d8f9c0edae3fc0f631285` |
| `permit-record-redacted-c6f2c45ab0f8dee2.png` | Solari Browser | A recorded browser rendered an official Delaware permit detail page after sensitive ownership and location fields were rewritten. | `c6f2c45ab0f8dee2292fbc9fe880c45993297fb3109791f6b5ef7a8551ab3f81` |

The browser session ID and signed replay URL are intentionally omitted because they are operational credentials and can expire. The desktop receipt is also intentionally absent: the earlier capture did not meet the current visible-content validation, so the adapter now rejects unchanged, undersized, partial, or non-PNG receipts. A fresh desktop receipt will be added only after a new run with a rotated Solari key passes those checks.
