"""Deterministic compiler from Canonical Need requirements to Worker contracts.

The MainAgent may describe *which registered semantic requirements* a user Need
contains, but it never owns concrete runtime policy.  This compiler resolves the
registered semantic key to the actual Slot/parameter contract, validates Worker
coverage and expands a compact Worker assignment into full CapabilityContracts.

This keeps dynamic orchestration in the LLM while keeping capability semantics,
source ownership, acceptance rules and Worker scope deterministic in code.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .registry import CapabilityRegistry
from .semantic_slots import slot_matches_patterns


def _violation(code: str, path: str, detail: str = ""):
    # Lazy import avoids capability<->collaboration package initialization cycles.
    from agent.collaboration.worker_contracts import WorkerContractViolation
    return WorkerContractViolation(code, path, detail)


class NeedRequirementCompiler:
    SCHEMA_VERSION = "need-requirement.v1"

    def __init__(self, registry: CapabilityRegistry, worker_directory: Any) -> None:
        self.registry = registry
        self.worker_directory = worker_directory

    def normalize_requirement(
        self,
        raw: dict[str, Any],
        *,
        need_id: str,
        index: int,
    ) -> dict[str, Any]:
        semantic_key = str(raw.get("semantic_key") or "").strip()
        if not semantic_key or not self.registry.semantic_requirement_exists(semantic_key):
            raise _violation(
                "unknown_need_semantic_requirement",
                f"$.needs[{need_id}].requirements[{index}]",
                semantic_key,
            )
        registered = self.registry.semantic_requirement(semantic_key)
        kind = str(registered.get("kind") or "slot").strip().lower()
        direction = str(raw.get("direction") or "input").strip().lower()
        if direction not in {"input", "output", "parameter"}:
            raise _violation(
                "invalid_need_requirement_direction",
                f"$.needs[{need_id}].requirements[{index}].direction",
                direction,
            )
        if kind == "parameter" and direction != "parameter":
            raise _violation(
                "parameter_semantic_must_be_parameter_direction",
                f"$.needs[{need_id}].requirements[{index}]",
                semantic_key,
            )
        if kind != "parameter" and direction == "parameter":
            raise _violation(
                "slot_semantic_cannot_be_parameter_direction",
                f"$.needs[{need_id}].requirements[{index}]",
                semantic_key,
            )

        row: dict[str, Any] = {
            "requirement_id": f"{need_id}-R{index + 1:02d}",
            "semantic_key": semantic_key,
            "direction": direction,
            "kind": kind,
            "semantic_role": str(registered.get("semantic_role") or semantic_key),
            "source_policy": str(registered.get("source_policy") or "system"),
            "satisfaction_rule": str(registered.get("satisfaction_rule") or "exists"),
            "required": bool(raw.get("required", True)),
            "required_paths": list(dict.fromkeys(
                str(item).strip()
                for item in raw.get("required_paths") or []
                if str(item).strip()
            )),
        }
        if kind == "parameter":
            row.update({
                "parameter_id": str(registered.get("parameter_id") or semantic_key),
                "satisfy_by": list(registered.get("satisfy_by") or []),
                "description": str(registered.get("description") or row["semantic_role"]),
                "expected_format": str(registered.get("expected_format") or ""),
            })
        else:
            row["slot_id"] = str(registered.get("slot_id") or semantic_key)
        return row

    def normalize_need_requirements(
        self,
        *,
        need_id: str,
        raw_requirements: list[dict[str, Any]] | None,
        strict: bool,
    ) -> list[dict[str, Any]]:
        rows = [dict(item) for item in raw_requirements or [] if isinstance(item, dict)]
        if strict and not rows:
            raise _violation(
                "canonical_need_requirements_required",
                f"$.needs[{need_id}].requirements",
            )
        normalized = [
            self.normalize_requirement(row, need_id=need_id, index=index)
            for index, row in enumerate(rows)
        ]
        if strict and not any(
            item["direction"] == "output" and item.get("required", True)
            for item in normalized
        ):
            raise _violation(
                "canonical_need_output_requirement_required",
                f"$.needs[{need_id}].requirements",
            )
        return normalized

    @staticmethod
    def requirement_index(intent_contract: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
        index: dict[str, tuple[str, dict[str, Any]]] = {}
        for need in intent_contract.get("needs") or []:
            need_id = str(need.get("need_id") or "")
            for req in need.get("requirements") or []:
                requirement_id = str(req.get("requirement_id") or "")
                if requirement_id:
                    index[requirement_id] = (need_id, dict(req))
        return index

    @staticmethod
    def output_slots_by_need(intent_contract: dict[str, Any]) -> dict[str, set[str]]:
        result: dict[str, set[str]] = defaultdict(set)
        for need in intent_contract.get("needs") or []:
            need_id = str(need.get("need_id") or "")
            for req in need.get("requirements") or []:
                if req.get("direction") == "output" and req.get("slot_id") and req.get("required", True):
                    result[need_id].add(str(req["slot_id"]))
        return dict(result)

    def validate_worker_call_need_outputs(
        self,
        *,
        intent_contract: dict[str, Any],
        worker_calls: list[dict[str, Any]],
    ) -> None:
        output_slots_by_need = self.output_slots_by_need(intent_contract)
        for need in intent_contract.get("needs") or []:
            if not bool(need.get("required", True)):
                continue
            need_id = str(need.get("need_id") or "")
            required_outputs = output_slots_by_need.get(need_id, set())
            if not required_outputs:
                continue
            realized = {
                str(slot)
                for call in worker_calls
                if need_id in {str(item) for item in call.get("covers_need_ids") or []}
                for slot in call.get("desired_output_slots") or []
                if str(slot)
            }
            missing = sorted(required_outputs - realized)
            if missing:
                raise _violation(
                    "need_required_output_not_covered_by_worker_calls",
                    "$.worker_calls",
                    f"{need_id}:{','.join(missing)}",
                )

    @staticmethod
    def _slot_requirement_from_semantic(req: dict[str, Any]) -> dict[str, Any]:
        return {
            "slot_id": str(req.get("slot_id") or ""),
            "semantic_role": str(req.get("semantic_role") or req.get("semantic_key") or ""),
            "source_policy": str(req.get("source_policy") or "system"),
            "satisfaction_rule": str(req.get("satisfaction_rule") or "exists"),
            "required": bool(req.get("required", True)),
            "cardinality": "one",
            "required_paths": list(req.get("required_paths") or []),
        }

    @staticmethod
    def _parameter_requirement_from_semantic(req: dict[str, Any]) -> dict[str, Any]:
        return {
            "parameter_id": str(req.get("parameter_id") or req.get("semantic_key") or ""),
            "semantic_role": str(req.get("semantic_role") or req.get("semantic_key") or ""),
            "source_policy": str(req.get("source_policy") or "user"),
            "satisfaction_rule": str(req.get("satisfaction_rule") or "one_of"),
            "required": bool(req.get("required", True)),
            "satisfy_by": list(req.get("satisfy_by") or []),
            "description": str(req.get("description") or req.get("semantic_role") or ""),
            "expected_format": str(req.get("expected_format") or ""),
        }

    def _slot_semantic_defaults(self, slot_id: str) -> dict[str, Any]:
        for item in self.registry.semantic_requirement_catalog():
            if item.get("kind") == "slot" and str(item.get("slot_id") or "") == slot_id:
                return {
                    "semantic_role": str(item.get("semantic_role") or slot_id),
                    "source_policy": str(item.get("source_policy") or "system"),
                    "satisfaction_rule": str(item.get("satisfaction_rule") or "exists"),
                }
        return {
            "semantic_role": slot_id,
            "source_policy": "system",
            "satisfaction_rule": "exists",
        }


    def compile_task_requirements(
        self,
        *,
        intent_contract: dict[str, Any],
        worker_calls: list[dict[str, Any]],
        initial_slots: set[str],
    ) -> list[dict[str, Any]]:
        """Deterministically assign Canonical Need requirements to selected Workers.

        MainAgent owns only ``Need -> WorkerCall``.  Once WorkerCalls have been
        selected, requirement ownership is a typed compilation problem:

        * output requirements identify the WorkerCall(s) that own each Need;
        * input/parameter requirements are attached to those output owners when
          their public Worker scope accepts the registered Slot/parameter;
        * the final presentation Worker consumes terminal business outputs so it
          cannot run before the actual business result exists;
        * SlotBinder later derives dependency edges from producer/consumer Slots.

        No LLM is used here and no Tool/private Worker information is inspected.
        """

        calls = [dict(call) for call in worker_calls or [] if isinstance(call, dict)]
        if not calls:
            raise _violation("worker_calls_required", "$.worker_calls")

        call_by_id: dict[str, dict[str, Any]] = {}
        scope_by_call: dict[str, dict[str, Any]] = {}
        for index, call in enumerate(calls):
            call_id = str(call.get("call_id") or f"WC{index + 1:02d}").strip()
            worker_id = str(call.get("worker_id") or "").strip().upper()
            if not call_id or call_id in call_by_id:
                raise _violation("duplicate_worker_call_id", "$.worker_calls", call_id)
            card = self.worker_directory.get(worker_id)
            call_by_id[call_id] = call
            scope_by_call[call_id] = self.registry.aggregate_scope(card.supported_boundary_ids)

        req_index = self.requirement_index(intent_contract)
        output_slots_by_need = self.output_slots_by_need(intent_contract)
        need_by_id = {
            str(need.get("need_id") or ""): dict(need)
            for need in intent_contract.get("needs") or []
            if isinstance(need, dict) and str(need.get("need_id") or "")
        }

        assignments: dict[str, dict[str, Any]] = {
            call_id: {
                "call_id": call_id,
                "requirement_ids": [],
                "additional_required_slots": [],
            }
            for call_id in call_by_id
        }

        def call_need_ids(call: dict[str, Any]) -> set[str]:
            return {str(item) for item in call.get("covers_need_ids") or [] if str(item)}

        def accepts_slot(call_id: str, slot_id: str) -> bool:
            return bool(slot_id) and slot_matches_patterns(
                slot_id, scope_by_call[call_id].get("accepted_input_patterns") or []
            )

        def accepts_parameter(call_id: str, req: dict[str, Any]) -> bool:
            patterns = scope_by_call[call_id].get("accepted_business_parameter_patterns") or []
            keys = [
                str(req.get("parameter_id") or ""),
                *[str(item) for item in req.get("satisfy_by") or [] if str(item)],
            ]
            keys = [key for key in keys if key]
            return bool(keys) and any(slot_matches_patterns(key, patterns) for key in keys)

        # A Need owner is a selected call that both covers the Need and promises
        # at least one of that Need's required output Slots.  This prevents data
        # provider Workers from being mistaken for the professional Worker that
        # actually owns the Need result.
        owner_calls_by_need: dict[str, list[str]] = {}
        for need_id, required_outputs in output_slots_by_need.items():
            owners: list[str] = []
            for call_id, call in call_by_id.items():
                if need_id not in call_need_ids(call):
                    continue
                desired = {str(item) for item in call.get("desired_output_slots") or [] if str(item)}
                if required_outputs.intersection(desired):
                    owners.append(call_id)
            if required_outputs and not owners:
                raise _violation(
                    "need_required_output_has_no_owner_worker",
                    "$.worker_calls",
                    f"{need_id}:{','.join(sorted(required_outputs))}",
                )
            owner_calls_by_need[need_id] = owners

        assigned_required: set[str] = set()
        for requirement_id, (need_id, req) in req_index.items():
            if req.get("direction") not in {"input", "parameter"}:
                continue
            owners = list(owner_calls_by_need.get(need_id) or [])
            if not owners:
                # Legacy/optional defensive fallback: only calls that explicitly
                # claim this Need may consume its requirement.
                owners = [
                    call_id for call_id, call in call_by_id.items()
                    if need_id in call_need_ids(call)
                ]

            if req.get("direction") == "parameter":
                eligible = [call_id for call_id in owners if accepts_parameter(call_id, req)]
            else:
                slot_id = str(req.get("slot_id") or "")
                eligible = [call_id for call_id in owners if accepts_slot(call_id, slot_id)]

            if not eligible:
                if bool(req.get("required", True)):
                    raise _violation(
                        "need_requirement_has_no_consumer_worker",
                        "$.worker_calls",
                        f"{requirement_id}:{req.get('semantic_key') or ''}",
                    )
                continue

            # If multiple output owners genuinely accept the same required fact,
            # each owner receives it.  This is deterministic and lets SlotBinder
            # express fan-out without another semantic LLM decision.
            for call_id in eligible:
                assignments[call_id]["requirement_ids"].append(requirement_id)
            if bool(req.get("required", True)):
                assigned_required.add(requirement_id)

        required_ids = {
            req_id for req_id, (_, req) in req_index.items()
            if bool(req.get("required", True)) and req.get("direction") in {"input", "parameter"}
        }
        missing = sorted(required_ids - assigned_required)
        if missing:
            raise _violation("required_need_requirement_unassigned", "$.worker_calls", ",".join(missing))

        # Presentation is a deterministic sink.  It consumes business outputs
        # that are not prerequisites of another business Need.  Therefore the
        # report waits for the true terminal professional result (analysis, risk
        # result, proposal, etc.) without an LLM inventing dependencies.
        business_need_ids = {
            need_id for need_id, need in need_by_id.items()
            if str(need.get("kind") or "business") != "presentation"
        }
        presentation_need_ids = set(need_by_id) - business_need_ids
        business_outputs = {
            slot
            for need_id in business_need_ids
            for slot in output_slots_by_need.get(need_id, set())
        }
        consumed_by_business = {
            str(req.get("slot_id") or "")
            for need_id in business_need_ids
            for req in need_by_id.get(need_id, {}).get("requirements") or []
            if req.get("direction") == "input" and str(req.get("slot_id") or "")
        }
        terminal_business_outputs = business_outputs - consumed_by_business
        selected_output_slots = {
            str(slot)
            for call in calls
            for slot in call.get("desired_output_slots") or []
            if str(slot)
        }
        terminal_business_outputs.intersection_update(selected_output_slots)

        for call_id, call in call_by_id.items():
            if not presentation_need_ids.intersection(call_need_ids(call)):
                continue
            extras = [
                slot for slot in sorted(terminal_business_outputs)
                if accepts_slot(call_id, slot)
            ]
            assignments[call_id]["additional_required_slots"].extend(extras)

        # Normalize/dedupe while preserving WorkerCall order.
        result: list[dict[str, Any]] = []
        for call_id in call_by_id:
            row = assignments[call_id]
            row["requirement_ids"] = list(dict.fromkeys(row["requirement_ids"]))
            row["additional_required_slots"] = list(dict.fromkeys(row["additional_required_slots"]))
            result.append(row)
        return result

    def expand_compact_tasks(
        self,
        *,
        intent_contract: dict[str, Any],
        worker_calls: list[dict[str, Any]],
        task_requirements: list[dict[str, Any]],
        initial_slots: set[str],
        request_mode: str,
    ) -> list[dict[str, Any]]:
        """Expand compact MainAgent assignments into full static contracts."""

        call_by_id = {str(call.get("call_id") or ""): dict(call) for call in worker_calls}
        if not call_by_id:
            raise _violation("worker_calls_required", "$.worker_calls")

        assignment_by_call: dict[str, dict[str, Any]] = {}
        for index, raw in enumerate(task_requirements or []):
            if not isinstance(raw, dict):
                raise _violation("compact_task_requirement_not_object", f"$.task_requirements[{index}]")
            call_id = str(raw.get("call_id") or "").strip()
            if call_id not in call_by_id:
                raise _violation("compact_task_unknown_call", f"$.task_requirements[{index}].call_id", call_id)
            if call_id in assignment_by_call:
                raise _violation("compact_task_duplicate_call", "$.task_requirements", call_id)
            assignment_by_call[call_id] = dict(raw)
        missing_calls = sorted(set(call_by_id) - set(assignment_by_call))
        if missing_calls:
            raise _violation("compact_task_assignment_missing_call", "$.task_requirements", ",".join(missing_calls))

        req_index = self.requirement_index(intent_contract)
        required_assignments = {
            req_id
            for req_id, (_, req) in req_index.items()
            if bool(req.get("required", True)) and req.get("direction") in {"input", "parameter"}
        }
        assigned_requirements: set[str] = set()
        all_selected_outputs = {
            str(slot)
            for call in worker_calls
            for slot in call.get("desired_output_slots") or []
            if str(slot)
        }
        allowed_additional_slots = set(initial_slots) | all_selected_outputs
        tasks: list[dict[str, Any]] = []

        for call_id, call in call_by_id.items():
            assignment = assignment_by_call[call_id]
            worker_id = str(call.get("worker_id") or "").strip().upper()
            card = self.worker_directory.get(worker_id)
            scope = self.registry.aggregate_scope(card.supported_boundary_ids)
            call_need_ids = {str(item) for item in call.get("covers_need_ids") or [] if str(item)}

            input_rows: list[dict[str, Any]] = []
            parameter_rows: list[dict[str, Any]] = []
            seen_inputs: set[str] = set()
            seen_parameters: set[str] = set()

            # Worker-level context requirements are static policy, so the LLM
            # never needs to repeat them in each plan.
            for slot_id in scope.get("required_context_slots") or []:
                slot_id = str(slot_id)
                if slot_id not in initial_slots or slot_id in seen_inputs:
                    continue
                defaults = self._slot_semantic_defaults(slot_id)
                input_rows.append({
                    "slot_id": slot_id,
                    **defaults,
                    "required": True,
                    "cardinality": "one",
                    "required_paths": [],
                })
                seen_inputs.add(slot_id)

            for requirement_id in assignment.get("requirement_ids") or []:
                requirement_id = str(requirement_id)
                if requirement_id not in req_index:
                    raise _violation(
                        "compact_task_unknown_requirement",
                        f"$.task_requirements[{call_id}].requirement_ids",
                        requirement_id,
                    )
                need_id, req = req_index[requirement_id]
                if need_id not in call_need_ids:
                    raise _violation(
                        "compact_requirement_assigned_outside_need_coverage",
                        f"$.task_requirements[{call_id}].requirement_ids",
                        f"{requirement_id}->{call_id}",
                    )
                if req.get("direction") == "output":
                    raise _violation(
                        "compact_output_requirement_cannot_be_input_assignment",
                        f"$.task_requirements[{call_id}].requirement_ids",
                        requirement_id,
                    )
                if req.get("direction") == "parameter":
                    parameter_id = str(req.get("parameter_id") or "")
                    if parameter_id and parameter_id not in seen_parameters:
                        parameter_rows.append(self._parameter_requirement_from_semantic(req))
                        seen_parameters.add(parameter_id)
                else:
                    slot_id = str(req.get("slot_id") or "")
                    if slot_id and slot_id not in seen_inputs:
                        input_rows.append(self._slot_requirement_from_semantic(req))
                        seen_inputs.add(slot_id)
                assigned_requirements.add(requirement_id)

            for slot_id in assignment.get("additional_required_slots") or []:
                slot_id = str(slot_id).strip()
                if not slot_id:
                    continue
                if slot_id not in allowed_additional_slots:
                    raise _violation(
                        "compact_additional_slot_has_no_known_source",
                        f"$.task_requirements[{call_id}].additional_required_slots",
                        slot_id,
                    )
                if not slot_matches_patterns(slot_id, scope.get("accepted_input_patterns") or []):
                    raise _violation(
                        "compact_additional_slot_outside_worker_scope",
                        f"$.task_requirements[{call_id}].additional_required_slots",
                        slot_id,
                    )
                if slot_id in seen_inputs:
                    continue
                defaults = self._slot_semantic_defaults(slot_id)
                input_rows.append({
                    "slot_id": slot_id,
                    **defaults,
                    "required": True,
                    "cardinality": "one",
                    "required_paths": [],
                })
                seen_inputs.add(slot_id)

            unsupported_inputs = sorted(
                row["slot_id"] for row in input_rows
                if not slot_matches_patterns(row["slot_id"], scope.get("accepted_input_patterns") or [])
            )
            if unsupported_inputs:
                raise _violation(
                    "compiled_need_input_outside_worker_scope",
                    f"$.task_requirements[{call_id}]",
                    ",".join(unsupported_inputs),
                )
            unsupported_parameters = sorted({
                key
                for row in parameter_rows
                for key in [row["parameter_id"], *row.get("satisfy_by", [])]
                if not slot_matches_patterns(key, scope.get("accepted_business_parameter_patterns") or [])
            })
            if unsupported_parameters:
                raise _violation(
                    "compiled_need_parameter_outside_worker_scope",
                    f"$.task_requirements[{call_id}]",
                    ",".join(unsupported_parameters),
                )

            desired_outputs = [str(item) for item in call.get("desired_output_slots") or [] if str(item)]
            max_effect = str(getattr(card, "max_effect_level", "read") or "read")
            effect_limit = "proposal" if request_mode == "proposal" and max_effect == "proposal" else "read"
            tasks.append({
                "worker_id": worker_id,
                "objective": str(call.get("objective") or "").strip(),
                "effect_limit": effect_limit,
                "priority": 1,
                "business_parameters": {},
                "contracts": [{
                    "description": str(call.get("objective") or "").strip(),
                    "required_inputs": input_rows,
                    "required_parameters": parameter_rows,
                    "promised_outputs": [
                        {"slot_id": slot_id, "provenance_required": True, "required_paths": []}
                        for slot_id in desired_outputs
                    ],
                    "acceptance_rule_ids": list(scope.get("allowed_acceptance_rule_ids") or []),
                    "forbidden_output_slots": [],
                    "criticality": "required",
                    "effect_limit": effect_limit,
                }],
            })

        missing_assignments = sorted(required_assignments - assigned_requirements)
        if missing_assignments:
            raise _violation(
                "required_need_requirement_unassigned",
                "$.task_requirements",
                ",".join(missing_assignments),
            )
        return tasks


__all__ = ["NeedRequirementCompiler"]
