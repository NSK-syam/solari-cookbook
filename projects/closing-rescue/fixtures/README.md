# Demo fixtures

These three synthetic Delaware property records are normalized, privacy-safe competition fixtures. They contain no borrower data, real owner names, or claims about actual homes. Their source shapes and citations mirror the live adapters, but values are deliberately frozen so network health cannot change the judged workflow.

- `clear.json`: recent matching permit and no material site modifier.
- `investigate.json`: completed permit query with no matching record; absence remains unknown.
- `inspect.json`: older permit record, limiting terrain/flood evidence, recent rainfall, and a near closing deadline.

The interface labels fixture mode. Live mode calls Mireye, Delaware Open Data, and NOAA directly.

## Competition portfolio

`portfolio/closing-rescue.json` is a frozen 47-loan, $14.2 million synthetic
Delaware portfolio. It contains property and operational data only. Stable loan
IDs and values make competition runs repeatable, and every record explicitly
carries `truth_class: "synthetic"`.

Most records use `fixture_scenario: "routine"`. Exactly four records are marked
as attention candidates with distinct scenario values:

- `priority`: the hero closing-rescue case.
- `permit_gap`: a case intended to represent missing permit evidence.
- `site_constraint`: a case intended to represent a property-site concern.
- `closing_deadline`: a case intended to represent imminent timing pressure.

These scenario labels identify fixture intent only; they do not implement or
imply portfolio priority scoring.
