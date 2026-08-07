from __future__ import annotations

from typing import Any

from .models import CapabilityContract, ContractCompletionReport


class CapabilityContractValidator:
    """Validate task contracts against a normalized Worker result."""

    def validate(
        self,
        *,
        contracts: list[CapabilityContract],
        produced_slots: set[str],
        result_status: str,
        result_payload: dict[str, Any] | None,
        evidence_refs: list[str] | None = None,
    ) -> list[ContractCompletionReport]:
        payload = dict(result_payload or {})
        reports: list[ContractCompletionReport] = []
        for contract in contracts:
            promised = set(contract.output_slots())
            satisfied = sorted(promised.intersection(produced_slots))
            missing = sorted(promised - produced_slots)
            failed_rules: list[str] = []
            if "schema_valid" in contract.acceptance_rule_ids and not isinstance(payload, dict):
                failed_rules.append("schema_valid")
            if "no_forbidden_output" in contract.acceptance_rule_ids:
                if set(contract.forbidden_output_slots).intersection(produced_slots):
                    failed_rules.append("no_forbidden_output")
            if "provenance_present" in contract.acceptance_rule_ids and promised:
                if not evidence_refs and not payload.get("provenance_refs") and not payload.get("sources"):
                    # Deterministic internal facts may expose source identifiers in
                    # nested records; the Worker adapter can set evidence_refs.
                    failed_rules.append("provenance_present")

            status = "completed"
            if result_status in {"need_context", "waiting_context"}:
                status = "need_context"
            elif result_status in {"blocked", "not_executed"}:
                status = "blocked"
            elif result_status in {"failed", "error"}:
                status = "failed"
            elif missing or failed_rules:
                status = "business_insufficient"
            elif payload.get("business_empty") is True or payload.get("found") is False:
                status = "business_empty"

            if status not in set(contract.allowed_terminal_states):
                failed_rules.append("terminal_state_not_allowed")
                status = "business_insufficient" if result_status not in {"failed", "error"} else "failed"

            reports.append(
                ContractCompletionReport(
                    contract_id=contract.contract_id,
                    status=status,
                    satisfied_outputs=satisfied,
                    missing_outputs=missing,
                    failed_acceptance_rules=failed_rules,
                    evidence_refs=list(evidence_refs or []),
                    limitations=[
                        *(["missing promised output slots"] if missing else []),
                        *(["acceptance rules failed"] if failed_rules else []),
                    ],
                )
            )
        return reports
