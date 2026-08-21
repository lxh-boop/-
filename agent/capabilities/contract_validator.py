from __future__ import annotations

from typing import Any

from .data_names import missing_required_paths
from .models import CapabilityContract, ContractCompletionReport


class CapabilityContractValidator:
    """Validate Worker contracts against materialized business-data names.

    Empty values are valid materialized data: the name is written only after a
    successful query/generation finishes, so ``[]``/``{}`` explicitly mean the
    completed business operation returned an empty value.
    """

    def validate(
        self,
        *,
        contracts: list[CapabilityContract],
        produced_data_names: set[str],
        materialized_data: dict[str, Any] | None,
        result_status: str,
        result_payload: dict[str, Any] | None,
        evidence_refs: list[str] | None = None,
    ) -> list[ContractCompletionReport]:
        payload = dict(result_payload or {})
        values = dict(materialized_data or {})
        reports: list[ContractCompletionReport] = []

        for contract in contracts:
            promised = set(contract.output_data_names())
            concrete = {name for name in values if name in promised}
            satisfied = sorted(promised.intersection(produced_data_names).intersection(concrete))
            missing = sorted(promised - set(satisfied))
            failed_rules: list[str] = []

            if "schema_valid" in contract.acceptance_rule_ids:
                for output in contract.promised_data:
                    if output.name not in concrete:
                        continue
                    if missing_required_paths(values.get(output.name), output.required_paths):
                        failed_rules.append("schema_valid")
                        break
            if "no_forbidden_output" in contract.acceptance_rule_ids:
                if set(contract.forbidden_data_names).intersection(values):
                    failed_rules.append("no_forbidden_output")

            status = "completed"
            if result_status in {"need_context", "waiting_context"}:
                status = "need_context"
            elif result_status in {"blocked", "not_executed"}:
                status = "blocked"
            elif result_status in {"failed", "error"}:
                status = "failed"
            elif missing or failed_rules:
                status = "business_insufficient"
            elif payload.get("business_empty") is True or (
                promised and all(values.get(name) in (None, {}, [], "") for name in promised if name in values)
            ):
                status = "business_empty"

            if status not in set(contract.allowed_terminal_states):
                failed_rules.append("terminal_state_not_allowed")
                status = "failed" if result_status in {"failed", "error"} else "business_insufficient"

            reports.append(ContractCompletionReport(
                contract_id=contract.contract_id,
                status=status,
                satisfied_outputs=satisfied,
                missing_outputs=missing,
                failed_acceptance_rules=list(dict.fromkeys(failed_rules)),
                evidence_refs=list(evidence_refs or []),
                limitations=[
                    *(["missing materialized promised business data"] if missing else []),
                    *(["acceptance rules failed"] if failed_rules else []),
                ],
            ))
        return reports
