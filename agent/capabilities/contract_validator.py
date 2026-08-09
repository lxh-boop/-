from __future__ import annotations

from typing import Any

from .models import CapabilityContract, ContractCompletionReport
from .semantic_slots import missing_required_paths


class CapabilityContractValidator:
    """Validate contracts against the one authoritative materialized Slot map."""

    def validate(
        self,
        *,
        contracts: list[CapabilityContract],
        produced_slots: set[str],
        materialized_slots: dict[str, Any] | None,
        result_status: str,
        result_payload: dict[str, Any] | None,
        evidence_refs: list[str] | None = None,
    ) -> list[ContractCompletionReport]:
        payload = dict(result_payload or {})
        values = dict(materialized_slots or {})
        reports: list[ContractCompletionReport] = []

        for contract in contracts:
            promised = set(contract.output_slots())
            concrete = {
                slot_id
                for slot_id, value in values.items()
                if slot_id in promised and value is not None
            }
            # A Slot is produced only when a concrete value exists. Completion
            # metadata and expected outputs are declarations, never data.
            satisfied = sorted(promised.intersection(produced_slots).intersection(concrete))
            missing = sorted(promised - set(satisfied))
            failed_rules: list[str] = []

            if "schema_valid" in contract.acceptance_rule_ids:
                if not isinstance(payload, dict) or not isinstance(values, dict):
                    failed_rules.append("schema_valid")
                else:
                    for output in contract.promised_outputs:
                        if output.slot_id not in concrete:
                            continue
                        # Capability-layer validation is structural and dynamic.
                        # schema_id remains metadata for Tool/transport contracts;
                        # no per-business Schema Registry is required here.
                        missing_paths = missing_required_paths(
                            values.get(output.slot_id),
                            getattr(output, "required_paths", []) or [],
                        )
                        if missing_paths:
                            failed_rules.append("schema_valid")
                            break

            if "no_forbidden_output" in contract.acceptance_rule_ids:
                if set(contract.forbidden_output_slots).intersection(values):
                    failed_rules.append("no_forbidden_output")

            if "provenance_present" in contract.acceptance_rule_ids and promised:
                if not evidence_refs and not payload.get("provenance_refs") and not payload.get("sources"):
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
                    failed_acceptance_rules=list(dict.fromkeys(failed_rules)),
                    evidence_refs=list(evidence_refs or []),
                    limitations=[
                        *(["missing materialized promised output slots"] if missing else []),
                        *(["acceptance rules failed"] if failed_rules else []),
                    ],
                )
            )
        return reports
