"""Auditable lender memo rendering from a validated decision snapshot."""

from __future__ import annotations

from septic_sentinel.models import CaseRecord, DecisionSnapshot, Evidence


class MemoCitationError(ValueError):
    pass


def render_memo(case: CaseRecord, decision: DecisionSnapshot, evidence: list[Evidence]) -> str:
    citations = {citation.id: citation for item in evidence for citation in item.citations}
    citation_numbers: dict[str, int] = {}

    def references(ids: list[str]) -> str:
        missing = set(ids) - set(citations)
        if missing:
            raise MemoCitationError(f"Unknown citation identifiers: {sorted(missing)}")
        numbers: list[int] = []
        for citation_id in ids:
            if citation_id not in citation_numbers:
                citation_numbers[citation_id] = len(citation_numbers) + 1
            numbers.append(citation_numbers[citation_id])
        return "".join(f"[{number}]" for number in sorted(set(numbers)))

    lines = [
        "# Septic Due-Diligence Memo",
        "",
        f"**Case:** {case.external_case_id}",
        f"**Property:** {case.address}",
        f"**Closing date:** {case.closing_date.isoformat()}",
        f"**Disposition:** {decision.result.disposition.value.upper()}",
        f"**Confidence:** {decision.result.confidence:.0%}",
        "",
        "## Observed facts",
        "",
    ]
    if decision.result.observed_facts:
        for fact in decision.result.observed_facts:
            lines.append(f"- {fact.statement} {references(fact.citation_ids)}")
    else:
        lines.append("- No citation-supported facts were available for this decision.")

    lines.extend(["", "## Agent inferences", ""])
    for inference in decision.result.inferences:
        lines.append(f"- **Inference:** {inference.statement}")

    lines.extend(["", "## Evidence gaps and conflicts", ""])
    gaps = decision.result.missing_evidence + decision.result.conflicts
    if gaps:
        lines.extend(f"- {item}" for item in gaps)
    else:
        lines.append("- No required evidence gaps or conflicts were identified.")

    lines.extend(
        [
            "",
            "## Recommended next action",
            "",
            decision.result.recommended_action,
            "",
            "## Sources",
            "",
        ]
    )
    ordered = sorted(citation_numbers.items(), key=lambda item: item[1])
    for citation_id, number in ordered:
        citation = citations[citation_id]
        url = str(citation.source_url) if citation.source_url else "Source URL unavailable"
        lines.append(
            f"[{number}] {citation.source_name} — {url} — retrieved "
            f"{citation.retrieved_at.isoformat()}"
        )

    lines.extend(
        [
            "",
            "---",
            "This memo is property-condition decision support. It is not a septic-system "
            "inspection, a diagnosis, a guarantee of condition, or a credit decision.",
        ]
    )
    return "\n".join(lines)
