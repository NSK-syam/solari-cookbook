"""Deterministic comparison of normalized claims over an explicit field registry."""

from __future__ import annotations

from collections.abc import Callable

from septic_sentinel.models import (
    ContradictionFinding,
    ContradictionKind,
    NormalizedClaim,
    TruthClass,
)

ComparisonRule = Callable[[NormalizedClaim, NormalizedClaim], ContradictionFinding | None]


class ContradictionEngine:
    """Compare supported scalar claims without interpreting prose or making allegations."""

    RULE_VERSION = "contradiction-rules-v1"

    def __init__(self) -> None:
        self._rules: dict[str, ComparisonRule] = {
            "septic_replacement_year": self._compare_septic_replacement_year,
        }

    def compare(
        self, left: NormalizedClaim, right: NormalizedClaim
    ) -> ContradictionFinding | None:
        if left.id == right.id:
            return self._finding(
                kind=ContradictionKind.UNSUPPORTED,
                claims=(left, right),
                summary="Claims with the same identity were not compared.",
                rule_id="unsupported-duplicate-claim-id",
            )
        if left.field != right.field:
            return self._finding(
                kind=ContradictionKind.UNSUPPORTED,
                claims=(left, right),
                summary="Claims for different fields were not compared.",
                rule_id="unsupported-different-fields",
            )

        rule = self._rules.get(left.field)
        if rule is None:
            return self._finding(
                kind=ContradictionKind.UNSUPPORTED,
                claims=(left, right),
                summary="No deterministic comparison rule exists for this field.",
                rule_id="unsupported-field",
            )
        return rule(left, right)

    def from_not_found(self, claim: NormalizedClaim) -> ContradictionFinding:
        return self._finding(
            kind=ContradictionKind.MISSING_CORROBORATION,
            claims=(claim,),
            summary="No matching cited record was found to corroborate the submitted claim.",
            rule_id="record-not-found",
        )

    def from_source_unavailable(
        self, claim: NormalizedClaim, source_name: str
    ) -> ContradictionFinding:
        if not isinstance(source_name, str) or not source_name.strip():
            raise ValueError("source_name must not be blank")
        source_name = source_name.strip()
        return self._finding(
            kind=ContradictionKind.SOURCE_UNAVAILABLE,
            claims=(claim,),
            summary="The external record source was unavailable, so the claim was not compared.",
            rule_id="source-unavailable",
            additional_source_names=(source_name,),
        )

    def _compare_septic_replacement_year(
        self, left: NormalizedClaim, right: NormalizedClaim
    ) -> ContradictionFinding | None:
        if type(left.value) is not int or type(right.value) is not int:
            return self._finding(
                kind=ContradictionKind.UNSUPPORTED,
                claims=(left, right),
                summary="The replacement-year rule requires strict integer values.",
                rule_id="unsupported-value-type",
            )
        if left.value == right.value:
            return None
        return self._finding(
            kind=ContradictionKind.DIRECT,
            claims=(left, right),
            summary="The compared replacement-year values differ.",
            rule_id="septic-replacement-year-mismatch",
        )

    def _finding(
        self,
        *,
        kind: ContradictionKind,
        claims: tuple[NormalizedClaim, ...],
        summary: str,
        rule_id: str,
        additional_source_names: tuple[str, ...] = (),
    ) -> ContradictionFinding:
        citation_ids = tuple(
            dict.fromkeys(
                citation_id
                for claim in claims
                if claim.truth_class is TruthClass.EXTERNAL_CITED
                for citation_id in claim.citation_ids
            )
        )
        source_names = tuple(dict.fromkeys(claim.source_name for claim in claims))
        source_names = tuple(dict.fromkeys((*source_names, *additional_source_names)))
        return ContradictionFinding(
            kind=kind,
            claim_ids=tuple(dict.fromkeys(claim.id for claim in claims)),
            citation_ids=citation_ids,
            source_names=source_names,
            summary=summary,
            rule_id=rule_id,
            rule_version=self.RULE_VERSION,
        )
