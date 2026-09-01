# Privacy, retention, and deletion

## Data minimization

Septic Sentinel processes property-condition evidence, a lender case identifier, closing date, approved vendor names, and a human approver identity. It does not request or store borrower names, income, credit data, protected-class data, payment details, or property-owner names. Live adapter payloads are normalized before model reasoning, and owner and geometry fields are removed from the model input.

## Credentials

Mireye, OpenAI, and Solari credentials remain in local credential stores or environment variables. They are excluded by `.gitignore`, never returned through the API, and recursively redacted from structured logs. Solari receipts contain session IDs and public artifact metadata, never connection endpoints, cookies, or keys.

## Solari artifacts

The Delaware discovery query selects an explicit allowlist that excludes `ownername`. The recorded browser hides DOM rows containing owner labels before taking the screenshot. Sandbox manifests use synthetic loan IDs and integer formula inputs only. Desktop receipts show a local, non-submittable synthetic form. Runtime artifacts live under the ignored `runtime-artifacts/` directory and are served only through hash-named files.

## Logs

Request logs contain generated request identifiers, route paths, status codes, and latency. They do not log request bodies or property addresses. Source latency and typed evidence failures appear in the case audit trail for development and demo inspection.

## Retention

The MVP retention target is 30 days. Fixture records are synthetic and may be retained with the repository. A production deployment must run a scheduled purge of expired cases, their evidence, and action artifacts after the configured retention period, subject to lender recordkeeping requirements.

## Local deletion

The MVP uses one local SQLite database configured by `SEPTIC_SENTINEL_DB_PATH`. Stop the service and remove that explicit database file to delete all locally stored cases. The application does not delete external Mireye, Delaware, NOAA, or OpenAI records; those services remain governed by their own retention policies.

## Competition mode

Fixture mode is the default. Its 47-loan portfolio and vendor options are synthetic, contain no owner or borrower information, and are clearly labeled in the interface.
