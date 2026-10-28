"""Exception catalogue and classification (docs/05 sections 9.1-9.3, ASM-029, DEC-07).

The catalogue rows come from config/exception_codes.yaml (the same rows S1 loads into ops.exception_code).
Catalogue order is the order of those rows; it decides decision_reason_code when several codes share the
deciding severity. Classification is a pure function of the codes found in one submission round.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.common.enums import ExceptionClass, Severity, WorkflowStatus

SEVERITY_ORDER = (Severity.HARD, Severity.CORRECTABLE, Severity.SOFT, Severity.INFO)
# Ties at equal severity (docs/05 9.2): SUSPICIOUS_PATTERN > POLICY_VIOLATION > DATA_QUALITY >
# NO_VALID_APPROVAL_PATH > RULE_CONFLICT.
CLASS_ORDER = (ExceptionClass.SUSPICIOUS_PATTERN, ExceptionClass.POLICY_VIOLATION, ExceptionClass.DATA_QUALITY,
               ExceptionClass.NO_VALID_APPROVAL_PATH, ExceptionClass.RULE_CONFLICT)
STATUS_BY_SEVERITY = {Severity.HARD: WorkflowStatus.REJECTED,
                      Severity.CORRECTABLE: WorkflowStatus.RETURNED_FOR_CORRECTION,
                      Severity.SOFT: WorkflowStatus.ESCALATED_FOR_REVIEW}


@dataclass(frozen=True)
class CodeInfo:
    code: str
    exception_class: str
    severity: str
    order: int


@dataclass
class Finding:
    code: str
    detail: str
    other_request_ids: list[str] = field(default_factory=list)   # or the line ids a line-level code refers to


class FindingSet:
    """One Finding per code, in the order the checks run; repeated hits collect the related ids."""

    def __init__(self) -> None:
        self.items: dict[str, Finding] = {}

    def add(self, code: str, detail: str, other: str | None = None) -> None:
        f = self.items.setdefault(code, Finding(code, detail))
        if other is not None and other not in f.other_request_ids:
            f.other_request_ids.append(other)
            f.detail = f"{detail}: {', '.join(f.other_request_ids)}"

    def findings(self) -> list[Finding]:
        return list(self.items.values())


@dataclass(frozen=True)
class Classification:
    exception_class: str            # NONE when no codes
    severity: str | None            # highest severity present
    status_after_validation: str    # REJECTED / RETURNED_FOR_CORRECTION / ESCALATED_FOR_REVIEW / PENDING_APPROVAL
    decision_reason_code: str | None


class ExceptionCatalogue:
    def __init__(self, rows: list[dict]) -> None:
        """rows: dicts with exception_code, exception_class, severity, in catalogue order."""
        self._codes = {r["exception_code"]: CodeInfo(r["exception_code"], r["exception_class"], r["severity"], i)
                       for i, r in enumerate(rows)}

    @classmethod
    def from_config(cls, exception_codes_cfg: dict) -> "ExceptionCatalogue":
        return cls([{"exception_code": c["code"], "exception_class": c["class"], "severity": c["severity"]}
                    for c in exception_codes_cfg["codes"]])

    def info(self, code: str) -> CodeInfo:
        try:
            return self._codes[code]
        except KeyError:
            raise KeyError(f"exception code {code} is not in the catalogue") from None

    def rejects_or_returns(self, codes) -> bool:
        """True when validation alone already decides REJECTED or RETURNED_FOR_CORRECTION: no routing then."""
        return any(self.info(c).severity in (Severity.HARD, Severity.CORRECTABLE) for c in codes)

    def classify(self, codes) -> Classification:
        """docs/05 9.2/9.3: the highest severity decides the route; INFO or nothing -> PENDING_APPROVAL."""
        infos = sorted({self.info(c) for c in codes}, key=lambda i: i.order)
        if not infos:
            return Classification(ExceptionClass.NONE.value, None, WorkflowStatus.PENDING_APPROVAL.value, None)
        top = min((i.severity for i in infos), key=SEVERITY_ORDER.index)
        deciding = [i for i in infos if i.severity == top]
        cls = min((i.exception_class for i in deciding), key=CLASS_ORDER.index)
        status = STATUS_BY_SEVERITY.get(top, WorkflowStatus.PENDING_APPROVAL)
        reason = deciding[0].code if top in STATUS_BY_SEVERITY else None
        return Classification(cls, top, status.value, reason)
