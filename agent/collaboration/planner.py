from __future__ import annotations

import json
import re
from typing import Any

from core.llm import LLMService
from core.llm.prompt_compaction import (
    compact_json_dumps,
    coordinator_result_for_replan,
    observation_for_replan,
    plan_schema_for_prompt,
    planning_catalog_for_prompt,
)

from agent.console_trace import flow_event

from .agent_directory import AgentDirectory
from .models import AccessMode, GraphAgentTask, GraphWorkerResult, ResultStatus, TaskStatus
from .worker_contracts import (
    WorkerContractViolation,
    array_schema,
    object_schema,
    string_schema,
    validate_dependency_ids,
    validate_schema,
)


class CoordinatorPlanningError(RuntimeError):
    pass


def _contains_private_implementation(value: str) -> bool:
    text = str(value or "").lower()
    blocked = (
        "tool",
        "cypher",
        "sql",
        "api endpoint",
        "database table",
        "tool_registry",
        "stock_code",
        "stock_codes",
        "ts_code",
        "security_scope",
        "route_agent_query",
        "intent router",
    )
    return any(item in text for item in blocked) or bool(
        re.search(r"\b[a-z]+\.[a-z_]+\b", text)
    )


TASK_INPUT_REFERENCE_SCHEMA = object_schema(
    {
        "from_task_id": string_schema(min_length=1),
        "expected_output_type": string_schema(min_length=1),
    },
    required=["from_task_id", "expected_output_type"],
)

# Worker-specific role names are declared in each public Worker card. Every
# value under ``inputs`` must nevertheless be a semantic upstream reference or
# an array of references. Direct runtime values such as focus_ref_ids, user_id,
# language, and as_of_time are code-bound args and never belong in ``inputs``.
TASK_INPUT_VALUE_SCHEMA = {
    "anyOf": [
        TASK_INPUT_REFERENCE_SCHEMA,
        array_schema(TASK_INPUT_REFERENCE_SCHEMA, min_items=1, max_items=8),
    ]
}
TASK_INPUTS_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": TASK_INPUT_VALUE_SCHEMA,
}

GOAL_CONTRACT_SCHEMA = object_schema(
    {
        "goal_summary": string_schema(min_length=1),
        "desired_output_types": array_schema(
            string_schema(min_length=1), min_items=1, max_items=8
        ),
        "required_information_slots": array_schema(
            string_schema(min_length=1), min_items=1, max_items=30
        ),
        "completion_criteria": array_schema(
            string_schema(min_length=1), min_items=1, max_items=16
        ),
        "constraints": array_schema({"type": "string"}, max_items=20),
        "access_mode": {
            "type": "string",
            "enum": [AccessMode.READ.value, AccessMode.WRITE.value],
            "readOnly": True,
            "description": (
                "Code-owned business-state access boundary. Analysis, risk, advice, "
                "proposal and reporting are READ unless a persistent business state is mutated."
            ),
        },
    },
    required=[
        "goal_summary",
        "desired_output_types",
        "required_information_slots",
        "completion_criteria",
        "constraints",
        "access_mode",
    ],
)

PLANNING_STATE_SCHEMA = object_schema(
    {
        "initial_available_information_slots": array_schema(
            string_schema(min_length=1), min_items=1, max_items=40
        ),
        "final_planned_information_slots": array_schema(
            string_schema(min_length=1), min_items=1, max_items=80
        ),
        "unmet_information_slots": array_schema(
            string_schema(min_length=1), min_items=0, max_items=30
        ),
        "stop_reason": string_schema(min_length=1),
    },
    required=[
        "initial_available_information_slots",
        "final_planned_information_slots",
        "unmet_information_slots",
        "stop_reason",
    ],
)

TASK_EXPECTED_OUTPUT_SCHEMA = object_schema(
    {
        "output_type": string_schema(min_length=1),
        "information_slots": array_schema(
            string_schema(min_length=1), min_items=1, max_items=20
        ),
        "coverage_requirement": string_schema(min_length=1),
        "freshness_requirement": string_schema(min_length=1),
        "authority_requirement": string_schema(min_length=1),
    },
    required=[
        "output_type",
        "information_slots",
        "coverage_requirement",
        "freshness_requirement",
        "authority_requirement",
    ],
)

TASK_INPUT_CONTRACT_SCHEMA = object_schema(
    {
        # These two fields are code-owned metadata. The LLM may omit them;
        # _prepare_payload deterministically derives the canonical values from
        # args/defaults and the selected task contract.
        "direct_arg_names": {
            **array_schema(
                string_schema(min_length=1), min_items=0, max_items=20
            ),
            "readOnly": True,
            "description": "Code-owned; omit from LLM output.",
        },
        "runtime_bound_args": {
            **array_schema(
                string_schema(min_length=1), min_items=0, max_items=20
            ),
            "readOnly": True,
            "description": "Code-owned; omit from LLM output.",
        },
        # These two fields are the semantic part owned by MainAgent planning.
        "upstream_information_slots": array_schema(
            string_schema(min_length=1), min_items=0, max_items=30
        ),
        "available_context_slots": array_schema(
            string_schema(min_length=1), min_items=0, max_items=30
        ),
    },
    required=[],
)

TASK_EXPECTED_EFFECT_SCHEMA = object_schema(
    {
        "goal_slots_satisfied": array_schema(
            string_schema(min_length=1), min_items=0, max_items=20
        ),
        "unlocks_information_slots": array_schema(
            string_schema(min_length=1), min_items=0, max_items=20
        ),
        "used_by_task_ids": array_schema(
            string_schema(min_length=1), min_items=0, max_items=12
        ),
    },
    required=[
        "goal_slots_satisfied",
        "unlocks_information_slots",
        "used_by_task_ids",
    ],
)

TASK_FAILURE_POLICY_SCHEMA = object_schema(
    {
        "missing_parameter": string_schema(min_length=1),
        "missing_context": string_schema(min_length=1),
        "tool_failure": string_schema(min_length=1),
        "business_empty": string_schema(min_length=1),
        "business_insufficient": string_schema(min_length=1),
    },
    required=[
        "missing_parameter",
        "missing_context",
        "tool_failure",
        "business_empty",
        "business_insufficient",
    ],
)

PLAN_SCHEMA = object_schema(
    {
        "goal_contract": GOAL_CONTRACT_SCHEMA,
        "planning_state": PLANNING_STATE_SCHEMA,
        "tasks": array_schema(
            object_schema(
                {
                    "task_id": string_schema(min_length=1),
                    "worker_id": string_schema(min_length=1),
                    "objective": string_schema(min_length=1),
                    "purpose": string_schema(min_length=1),
                    "why_selected": string_schema(min_length=1),
                    "task_type": string_schema(min_length=1),
                    "args": object_schema({}, additional_properties=True),
                    "inputs": TASK_INPUTS_SCHEMA,
                    "input_contract": TASK_INPUT_CONTRACT_SCHEMA,
                    "expected_output": TASK_EXPECTED_OUTPUT_SCHEMA,
                    "expected_effect": TASK_EXPECTED_EFFECT_SCHEMA,
                    "completion_criteria": array_schema(
                        string_schema(min_length=1), min_items=1, max_items=16
                    ),
                    "failure_policy": TASK_FAILURE_POLICY_SCHEMA,
                    "replan_triggers": array_schema(
                        string_schema(min_length=1), min_items=1, max_items=16
                    ),
                    "constraints": array_schema({"type": "string"}),
                    "expected_output_type": string_schema(min_length=1),
                    "priority": {"type": "integer"},
                },
                required=[
                    "task_id",
                    "worker_id",
                    "objective",
                    "purpose",
                    "why_selected",
                    "task_type",
                    "args",
                    "inputs",
                    "input_contract",
                    "expected_output",
                    "expected_effect",
                    "completion_criteria",
                    "failure_policy",
                    "replan_triggers",
                    "constraints",
                    "expected_output_type",
                    "priority",
                ],
            ),
            min_items=1,
            max_items=10,
        ),
    },
    required=["goal_contract", "planning_state", "tasks"],
)

PLANNER_CONTRACT_EXAMPLES = {
    "root_task_inputs": {"inputs": {}},
    "single_upstream_input": {
        "inputs": {
            "current_state": {
                "from_task_id": "T01",
                "expected_output_type": "PortfolioAnalysisResult",
            }
        }
    },
    "multiple_upstream_inputs": {
        "inputs": {
            "risk_constraints": {
                "from_task_id": "T02",
                "expected_output_type": "PortfolioRiskResult",
            },
            "supporting_analysis": [
                {
                    "from_task_id": "T03",
                    "expected_output_type": "UserProfileResult",
                },
                {
                    "from_task_id": "T04",
                    "expected_output_type": "ModelPredictionResult",
                },
            ],
        }
    },
    "invalid_unwrapped_reference": {
        "inputs": {
            "from_task_id": "T01",
            "expected_output_type": "PortfolioAnalysisResult",
        }
    },
    "input_contract": {},
}


def _repair_capability_catalog(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep exact structural contracts required to repair a candidate plan."""

    worker_rows: list[dict[str, Any]] = []
    for worker in cards:
        task_rows: list[dict[str, Any]] = []
        for task in worker.get("task_contracts") or []:
            task_rows.append(
                {
                    key: task.get(key)
                    for key in (
                        "task_type",
                        "args_schema",
                        "semantic_inputs_schema",
                        "output_type",
                        "consumes_information_slots",
                        "produces_information_slots",
                        "required_context_slots",
                        "allowed_request_modes",
                        "access_mode",
                    )
                }
            )
        worker_rows.append(
            {
                "worker_id": worker.get("worker_id"),
                "agent_id": worker.get("agent_id"),
                "task_contracts": task_rows,
            }
        )
    return worker_rows



class CoordinatorPlanner:
    """Goal-constrained forward Worker-DAG planner.

    MainAgent first defines a GoalContract and the information slots already
    available from the request context. It then expands forward: select only a
    currently executable capability that satisfies an unmet goal slot or unlocks
    a necessary downstream capability, attach a per-task TaskExpectation, update
    the virtual information state, and stop at the minimal sufficient DAG.

    Runtime code still derives dependency IDs only from explicit semantic input
    references. The validator checks generic capability contracts and forward
    information-state consistency; it never hard-codes a business Worker chain.
    """

    def __init__(self, directory: AgentDirectory, *, llm_service: LLMService) -> None:
        self.directory = directory
        self.llm_service = llm_service

    @staticmethod
    def _initial_information_slots(
        *,
        request_mode: str,
        focus_refs: list,
        context_refs: list,
        memory_summary: str,
    ) -> list[str]:
        """Build the code-owned starting state for forward planning."""

        slots = ["user_request", "user_identity", "reply_language"]
        if memory_summary:
            slots.append("session_memory_summary")
        if focus_refs:
            slots.extend(["authoritative_graph_refs", "authoritative_financial_entities"])
            security_refs = [
                ref for ref in focus_refs
                if str(getattr(ref, "node_id", "")).startswith("cn:security:")
            ]
            if security_refs:
                slots.append("authoritative_security_entities")
            if len(security_refs) >= 2:
                slots.append("multiple_authoritative_financial_entities")
            if any(str(getattr(ref, "role", "")) == "portfolio_snapshot" for ref in focus_refs):
                slots.append("portfolio_references")
        if context_refs:
            slots.append("context_graph_refs")
        if str(request_mode or "") == "proposal":
            slots.extend(["explicit_change_intent", "proposal_permission"])
        else:
            slots.append("analysis_permission")
        return list(dict.fromkeys(slots))

    @staticmethod
    def _authoritative_runtime_values(
        *,
        focus_refs: list,
        context_refs: list,
        user_id: str,
        reply_language: str,
        as_of_time: str,
        run_id: str,
    ) -> dict[str, Any]:
        focus_ref_ids = [
            str(getattr(ref, "node_id", "") or "").strip()
            for ref in focus_refs
        ]
        context_ref_ids = [
            str(getattr(ref, "node_id", "") or "").strip()
            for ref in context_refs
        ]
        focus_ref_ids = [item for item in focus_ref_ids if item]
        context_ref_ids = [item for item in context_ref_ids if item]
        return {
            "focus_ref_ids": list(dict.fromkeys(focus_ref_ids)),
            "context_ref_ids": list(dict.fromkeys(context_ref_ids)),
            "all_ref_ids": list(
                dict.fromkeys([*focus_ref_ids, *context_ref_ids])
            ),
            "user_id": str(user_id or "default"),
            "reply_language": str(reply_language or "zh"),
            "as_of_time": str(as_of_time or ""),
            "run_id": str(run_id or ""),
        }

    def _prepare_payload(
        self,
        payload: dict[str, Any],
        *,
        runtime_values: dict[str, Any],
        authoritative_initial_information_slots: set[str] | None = None,
        request_mode: str = "",
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Bind code-owned args and isolate upstream WorkerResult references.

        MainAgent still owns Worker selection and every semantic edge. Runtime
        only supplies authoritative values that already exist outside the LLM
        plan. A misplaced code-owned value under ``inputs`` is removed from the
        semantic input map and recorded in the audit; no Worker or edge is
        inserted, removed, or rewired.
        """

        rows = [dict(item) for item in payload.get("tasks") or []]
        prepared_rows: list[dict[str, Any]] = []
        audit_rows: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            worker_id = str(row.get("worker_id") or "").upper()
            try:
                card = self.directory.get(worker_id)
            except KeyError:
                prepared_rows.append(row)
                continue

            args = dict(row.get("args") or {})
            inputs = dict(row.get("inputs") or {})
            bound: dict[str, Any] = {}
            defaults_applied: dict[str, Any] = {}
            removed_from_inputs: list[str] = []
            task_type = str(row.get("task_type") or "")
            for arg_name, default_value in card.default_args_for(task_type).items():
                if arg_name not in args or args.get(arg_name) in (None, ""):
                    args[str(arg_name)] = default_value
                    defaults_applied[str(arg_name)] = default_value
            bindings = card.authoritative_bindings_for(task_type)
            for arg_name, source_name in bindings.items():
                value = runtime_values.get(str(source_name))
                args[str(arg_name)] = value
                bound[str(arg_name)] = value
                if arg_name in inputs:
                    inputs.pop(arg_name, None)
                    removed_from_inputs.append(str(arg_name))

            # direct_arg_names and runtime_bound_args are compiler-owned
            # metadata. MainAgent plans semantic slots, while code derives these
            # fields from the selected task contract and the final bound args.
            input_contract = dict(row.get("input_contract") or {})
            canonical_runtime_args = sorted(str(name) for name in bindings)
            canonical_direct_args = sorted(
                str(name) for name in set(args) - set(bindings)
            )
            previous_code_owned = {
                "direct_arg_names": list(
                    input_contract.get("direct_arg_names") or []
                ),
                "runtime_bound_args": list(
                    input_contract.get("runtime_bound_args") or []
                ),
            }
            input_contract["direct_arg_names"] = canonical_direct_args
            input_contract["runtime_bound_args"] = canonical_runtime_args

            prepared = dict(row)
            prepared["worker_id"] = worker_id
            prepared["args"] = args
            prepared["inputs"] = inputs
            prepared["input_contract"] = input_contract
            prepared_rows.append(prepared)
            code_owned_changed = previous_code_owned != {
                "direct_arg_names": canonical_direct_args,
                "runtime_bound_args": canonical_runtime_args,
            }
            if (
                bound
                or defaults_applied
                or removed_from_inputs
                or code_owned_changed
            ):
                audit_rows.append(
                    {
                        "task_index": index,
                        "task_id": str(row.get("task_id") or ""),
                        "worker_id": worker_id,
                        "authoritative_args_bound": sorted(bound),
                        "default_args_applied": dict(defaults_applied),
                        "misplaced_runtime_args_removed_from_inputs": sorted(
                            removed_from_inputs
                        ),
                        "input_contract_code_owned_fields": {
                            "direct_arg_names": canonical_direct_args,
                            "runtime_bound_args": canonical_runtime_args,
                        },
                    }
                )
        # Compile information-state metadata from the authoritative context and
        # the semantic WorkerResult references. These fields do not choose a
        # Worker or invent an edge; they describe the plan already produced by
        # MainAgent and therefore should not consume a schema-repair LLM call.
        initial_slots = set(authoritative_initial_information_slots or set())
        output_slots_by_task = {
            str(row.get("task_id") or ""): {
                str(item)
                for item in dict(row.get("expected_output") or {}).get("information_slots") or []
                if str(item or "").strip()
            }
            for row in prepared_rows
        }
        for row in prepared_rows:
            task_id = str(row.get("task_id") or "")
            canonical_inputs = self._canonical_inputs(row.get("inputs") or {})
            dependency_ids = {
                str(item.get("from_task_id") or "")
                for values in canonical_inputs.values()
                for item in values
                if str(item.get("from_task_id") or "").strip()
            }
            upstream_slots = sorted(
                {
                    slot
                    for dependency_id in dependency_ids
                    for slot in output_slots_by_task.get(dependency_id, set())
                }
            )
            try:
                card = self.directory.get(str(row.get("worker_id") or ""))
                contract = card.task_contract(str(row.get("task_type") or ""))
                context_slots = sorted(
                    set(contract.required_context_slots).intersection(initial_slots)
                )
            except KeyError:
                context_slots = []
            input_contract = dict(row.get("input_contract") or {})
            input_contract["upstream_information_slots"] = upstream_slots
            input_contract["available_context_slots"] = context_slots
            row["input_contract"] = input_contract
            for audit in audit_rows:
                if str(audit.get("task_id") or "") == task_id:
                    audit.setdefault("input_contract_code_owned_fields", {}).update({
                        "upstream_information_slots": upstream_slots,
                        "available_context_slots": context_slots,
                    })
                    break
            else:
                audit_rows.append({
                    "task_id": task_id,
                    "worker_id": str(row.get("worker_id") or ""),
                    "authoritative_args_bound": [],
                    "default_args_applied": {},
                    "misplaced_runtime_args_removed_from_inputs": [],
                    "input_contract_code_owned_fields": {
                        "direct_arg_names": list(input_contract.get("direct_arg_names") or []),
                        "runtime_bound_args": list(input_contract.get("runtime_bound_args") or []),
                        "upstream_information_slots": upstream_slots,
                        "available_context_slots": context_slots,
                    },
                })

        goal_contract = dict(payload.get("goal_contract") or {})
        mode = str(request_mode or "").strip().lower()
        # MainAgent may express the semantic request mode, but the business-state
        # access boundary is compiled by the runtime. Analysis and run-local
        # proposals are READ. Persistent mutation requires the separate WRITE flow.
        if mode in {"analysis", "proposal"}:
            goal_contract["access_mode"] = AccessMode.READ.value
        planning_state = dict(payload.get("planning_state") or {})
        if initial_slots:
            all_output_slots = {
                slot
                for slots in output_slots_by_task.values()
                for slot in slots
            }
            final_slots = initial_slots | all_output_slots
            required_slots = {
                str(item)
                for item in goal_contract.get("required_information_slots") or []
                if str(item or "").strip()
            }
            planning_state["initial_available_information_slots"] = sorted(initial_slots)
            planning_state["final_planned_information_slots"] = sorted(final_slots)
            planning_state["unmet_information_slots"] = sorted(required_slots - final_slots)

        return {
            "goal_contract": goal_contract,
            "planning_state": planning_state,
            "tasks": prepared_rows,
        }, {"tasks": audit_rows}

    def _validate_planner_field_placement(self, payload: dict[str, Any]) -> None:
        """Validate the semantic-role-to-reference shape under ``inputs``."""

        rows = payload.get("tasks")
        if not isinstance(rows, list):
            return
        issues: list[str] = []
        for index, raw_row in enumerate(rows):
            if not isinstance(raw_row, dict):
                continue
            worker_id = str(raw_row.get("worker_id") or "").upper()
            task_type = str(raw_row.get("task_type") or "")
            try:
                card = self.directory.get(worker_id)
                contract = card.task_contract(task_type)
            except KeyError:
                continue
            inputs = raw_row.get("inputs")
            if not isinstance(inputs, dict):
                continue
            args_properties = dict(contract.args_schema.get("properties") or {})
            runtime_bound = set(contract.authoritative_arg_bindings)
            semantic_roles = set(contract.upstream_input_bindings)
            move_to_args: list[str] = []
            omit_runtime: list[str] = []
            unwrapped_reference_fields: list[str] = []
            unknown_roles: list[str] = []
            malformed_reference_roles: list[str] = []
            for raw_name, value in inputs.items():
                name = str(raw_name or "").strip()
                if not name:
                    continue
                if name in {"from_task_id", "expected_output_type"}:
                    unwrapped_reference_fields.append(name)
                    continue
                if name in runtime_bound:
                    omit_runtime.append(name)
                    continue
                if name in args_properties:
                    move_to_args.append(name)
                    continue
                if name not in semantic_roles:
                    unknown_roles.append(name)
                    continue
                values = value if isinstance(value, list) else [value]
                if not values or not all(
                    isinstance(item, dict)
                    and set(item) == {"from_task_id", "expected_output_type"}
                    and str(item.get("from_task_id") or "").strip()
                    and str(item.get("expected_output_type") or "").strip()
                    for item in values
                ):
                    malformed_reference_roles.append(name)
            if (
                move_to_args
                or omit_runtime
                or unwrapped_reference_fields
                or unknown_roles
                or malformed_reference_roles
            ):
                task_id = str(raw_row.get("task_id") or f"index_{index}")
                details: list[str] = [f"task={task_id}"]
                if move_to_args:
                    details.append(
                        "move_to_args=" + ",".join(sorted(move_to_args))
                    )
                if omit_runtime:
                    details.append(
                        "omit_runtime_bound_from_inputs="
                        + ",".join(sorted(omit_runtime))
                    )
                if unwrapped_reference_fields:
                    details.append(
                        "wrap_reference_under_semantic_role="
                        + ",".join(sorted(unwrapped_reference_fields))
                    )
                if unknown_roles:
                    details.append(
                        "unknown_semantic_input_roles="
                        + ",".join(sorted(unknown_roles))
                    )
                if malformed_reference_roles:
                    details.append(
                        "malformed_reference_roles="
                        + ",".join(sorted(malformed_reference_roles))
                    )
                issues.append(";".join(details))
        if issues:
            raise WorkerContractViolation(
                "planner_field_placement_error",
                "$.tasks",
                " | ".join(issues)
                + " | inputs_shape=semantic_role_to_reference;"
                "reference_fields=from_task_id+expected_output_type;"
                "root_task_inputs_must_be_empty_object;"
                "ordinary_args_belong_in_args;"
                "runtime_values_must_be_omitted_from_args_and_inputs",
            )

    @staticmethod
    def _canonical_inputs(value: Any) -> dict[str, list[dict[str, str]]]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, list[dict[str, str]]] = {}
        for raw_role, raw_value in value.items():
            role = str(raw_role or "").strip()
            if not role:
                continue
            raw_items = raw_value if isinstance(raw_value, list) else [raw_value]
            items: list[dict[str, str]] = []
            seen: set[tuple[str, str]] = set()
            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    continue
                task_id = str(raw_item.get("from_task_id") or "").strip()
                output_type = str(
                    raw_item.get("expected_output_type") or ""
                ).strip()
                if not task_id:
                    continue
                key = (task_id, output_type)
                if key in seen:
                    continue
                seen.add(key)
                items.append(
                    {
                        "from_task_id": task_id,
                        "expected_output_type": output_type,
                    }
                )
            if items:
                result[role] = items
        return result

    def _compile_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Compile semantic inputs into executor dependencies without new edges."""

        rows = [dict(item) for item in payload.get("tasks") or []]
        output_type_by_task = {
            str(row.get("task_id") or ""): str(
                row.get("expected_output_type") or ""
            )
            for row in rows
        }
        compiled_rows: list[dict[str, Any]] = []
        for row in rows:
            task_id = str(row.get("task_id") or "")
            worker_id = str(row.get("worker_id") or "")
            canonical_inputs = self._canonical_inputs(row.get("inputs") or {})
            dependencies = self.directory.validate_task_inputs(
                worker_id,
                canonical_inputs,
                task_type=str(row.get("task_type") or ""),
                task_id=task_id,
                output_type_by_task=output_type_by_task,
                path=f"$.tasks[{task_id}].inputs",
            )
            compiled = dict(row)
            compiled["inputs"] = canonical_inputs
            compiled["dependency_task_ids"] = dependencies
            compiled_rows.append(compiled)
        return {
            "goal_contract": dict(payload.get("goal_contract") or {}),
            "planning_state": dict(payload.get("planning_state") or {}),
            "tasks": compiled_rows,
            "dependency_derivation": "compiled_from_semantic_inputs",
        }

    def plan(
        self,
        *,
        query: str,
        request_mode: str,
        session_id: str,
        run_id: str,
        user_id: str,
        focus_refs: list,
        context_refs: list,
        memory_summary: str,
        language: str = "zh",
        as_of_time: str = "",
    ) -> tuple[list[GraphAgentTask], dict[str, Any]]:
        mode = str(request_mode or "analysis").strip().lower()
        if mode not in {"analysis", "proposal"}:
            raise CoordinatorPlanningError(
                f"unsupported_agent_request_mode:{mode}"
            )

        cards = planning_catalog_for_prompt(
            self.directory.planning_catalog(), request_mode=mode
        )
        prompt_plan_schema = plan_schema_for_prompt(PLAN_SCHEMA)
        flow_event(
            "LLM_PROMPT_COMPACTION_APPLIED",
            {
                "version": "v18.4",
                "stage": "graph_coordinator_planner",
                "request_mode": mode,
                "worker_count": len(cards),
                "task_contract_count": sum(
                    len(item.get("task_contracts") or []) for item in cards
                ),
                "catalog_chars": len(compact_json_dumps(cards)),
                "schema_chars": len(compact_json_dumps(prompt_plan_schema)),
                "llm_decision_owner": "main_agent",
            },
            run_id=run_id,
        )
        reply_language = "en" if language == "en" else "zh"
        runtime_values = self._authoritative_runtime_values(
            focus_refs=focus_refs,
            context_refs=context_refs,
            user_id=str(user_id or "default"),
            reply_language=reply_language,
            as_of_time=str(as_of_time or ""),
            run_id=run_id,
        )
        authoritative_ref_ids = {
            str(ref.node_id) for ref in [*focus_refs, *context_refs]
        }
        initial_information_slots = self._initial_information_slots(
            request_mode=mode,
            focus_refs=focus_refs,
            context_refs=context_refs,
            memory_summary=memory_summary,
        )

        def validate(payload: dict[str, Any]) -> None:
            try:
                prepared_payload, _ = self._prepare_payload(
                    payload,
                    runtime_values=runtime_values,
                    authoritative_initial_information_slots=set(initial_information_slots),
                    request_mode=mode,
                )
                self._validate_payload(
                    prepared_payload,
                    request_mode=mode,
                    authoritative_ref_ids=authoritative_ref_ids,
                    authoritative_user_id=str(user_id or "default"),
                    reply_language=reply_language,
                    user_request=query,
                    authoritative_initial_information_slots=set(initial_information_slots),
                )
            except (WorkerContractViolation, KeyError) as exc:
                raise CoordinatorPlanningError(str(exc)) from exc

        system = (
            "你是系统唯一的 MainAgent Worker 编排器。只能依据 user_request、request_mode、当前可用信息、"
            "GraphRef、会话摘要和 worker_capability_catalog 规划，禁止使用预设业务链路或固定 Worker 顺序。"
            "不要根据 Worker 名称猜测能力；必须阅读每个 task_contract 的 consumes_information_slots、"
            "produces_information_slots、required_context_slots、coverage_semantics、freshness_semantics、"
            "authority_level、args_schema、semantic_inputs_schema、正反例、完成标准和 access_mode。"
            "worker_capability_catalog 已由程序做无损规划视图压缩：args_schema 使用 required、fields、"
            "runtime_bound_args 表示原参数约束；semantic_inputs_schema 使用 required_roles 和 roles，"
            "每个 role 明确 allowed_output_types、required、cardinality、min_results、max_results。"
            "目录中只省略当前 request_mode 或 READ 边界下必然不合法的能力，MainAgent仍须在全部合法能力中自主选择。"
            "规划采用目标约束的正向扩展，不使用反向递归。第一步生成 goal_contract：忠实保留用户最终目标，"
            "列出 desired_output_types、required_information_slots、completion_criteria 和 constraints。access_mode 由程序固定为 READ，MainAgent 不得把分析、风险、建议、待审批 Proposal 或报告视为 WRITE。"
            "第二步基于 authoritative_initial_information_slots 规划；initial、final 和 unmet 三个信息槽位字段"
            "由程序在校验前生成，LLM只输出 planning_state.stop_reason。"
            "第三步从当前虚拟信息状态向前规划。每一轮只考虑 required_context_slots 已满足、直接参数可提供、"
            "必需 semantic inputs 已有生产者的 task_contract；从可执行候选中选择能满足尚未完成目标槽位，"
            "或能解锁目标必需后续能力的最小任务。选择后把该任务 expected_output.information_slots 加入虚拟状态，"
            "继续下一轮，直到所有 required_information_slots 和 desired_output_types 都有生产者。"
            "不能因为某能力可能有帮助、信息更全面或顺便可查就加入任务。新闻、公告、外部证据、模型信号、"
            "图影响分析都不是持仓建议的默认必选项，只有用户目标或已选下游合同明确需要时才能加入。"
            "一个任务必须满足至少一项：直接覆盖 goal_contract.required_information_slots；"
            "或其输出被某个已规划下游任务明确消费；或生成 FinalReport。"
            "所有目标已覆盖后立即停止并填写明确 stop_reason；final 和 unmet 信息槽位由程序根据任务输出计算。"
            "goal_summary 和 completion_criteria 不得声称会使用模型信号、外部证据、图关系或其他可选材料，"
            "除非 required_information_slots 明确需要它且当前计划确实选择了生产该槽位的任务。"
            "连续一轮不能新增目标槽位或解锁能力时停止并让适当能力返回 need_context。"
            "每个任务必须同步生成 TaskExpectation：purpose 说明它在本次目标中的作用；why_selected 说明为何当前可执行且有贡献；"
            "input_contract 只输出空对象 {}。upstream_information_slots、available_context_slots、direct_arg_names 与 runtime_bound_args "
            "均由程序根据语义 inputs、权威初始上下文、最终 args 和能力合同生成。"
            "expected_output 必须包含能力卡允许的 output_type、此次需要的信息槽位、覆盖范围、新鲜度和权威来源；"
            "expected_effect 说明直接满足哪些目标槽位、解锁哪些后续信息、会被哪些下游任务使用；"
            "completion_criteria 必须可用于执行后判断任务是否真正完成，不得只写返回某类型；"
            "failure_policy 必须分别处理 missing_parameter、missing_context、tool_failure、business_empty、business_insufficient；"
            "replan_triggers 必须列出类型正确但覆盖不足、数据过期、权威来源不符、必需字段缺失等触发条件。"
            "MainAgent不能要求能力卡没有声明的覆盖范围。例如 top_k_cross_section 不保证覆盖全部持仓；"
            "若本次目标需要其他覆盖，必须正向选择另一个当前可执行能力补充，而不是让 Worker 或报告器猜测。"
            "事实来源必须可追溯：证券、组合、用户画像、风险事实和业务结论只能来自 user_request 中的明确内容、"
            "程序提供的 GraphRef/上下文槽位或上游 WorkerResult。不得自行补造证券代码、证券名称、公告主题、"
            "风险偏好、风险暴露或用户约束；constraints 只能保留用户明确限制和系统副作用边界。"
            "args 只写 args_schema 允许的普通业务参数；runtime_bound_args 的值由程序绑定，必须从 args 和 inputs 省略。"
            "inputs 必须是 semantic role 到 WorkerResult 引用的映射。根任务写 inputs={}；有依赖时，"
            "role 的值必须是 {from_task_id, expected_output_type} 或该对象数组，绝不能把 from_task_id 和"
            "expected_output_type 直接放在 inputs 顶层。dependency_task_ids 由程序从 inputs 生成，MainAgent不得输出或发明。"
            "analysis 模式不生成 Proposal；proposal 模式允许形成仅存在于当前 Run 的待审批 Proposal。两者都属于 READ，禁止选择任何 access_mode=write 的 Worker。"
            "报告 Worker 只汇总已有终端专业结果，不能替代事实查询、研究、风险分析或 Proposal 生成。"
            "若某个上游结果已经被另一个已选专业结果消费并形成更高层结构化结论，报告任务只引用该终端结果，"
            "不得再次引用传递性的原始结果；实体分析报告应引用 EntityAnalysisResult，而不是同时引用其 EvidenceCollectionResult。"
            "summarize_results 只用于用户明确要求压缩已有结果，不能用于绕过 write_report 的输入合同。"
            "objective 和 purpose 只写业务子目标，不得包含 Tool、函数、API、数据库或实现细节。"
            "在不缺少任何必填字段和语义的前提下，所有自然语言字段只写完成该字段所需的一条简洁句子；"
            "不要在 goal_summary、objective、purpose、why_selected、completion_criteria 和 constraints 之间重复同一句话或同义内容。"
            "最终严格输出符合 worker_dag_output_schema 的 JSON，不要 Markdown，不要解释。"
        )
        event_names = {
            "request_started": "LOCAL_LLM_REQUEST_STARTED",
            "response_received": "LOCAL_LLM_RESPONSE_RECEIVED",
            "candidate_generated": "WORKER_PLAN_CANDIDATE_GENERATED",
            "validation_succeeded": "WORKER_PLAN_VALIDATION_SUCCEEDED",
            "validation_failed": "WORKER_PLAN_VALIDATION_FAILED",
            "repair_started": "WORKER_PLAN_REPAIR_STARTED",
            "repair_response_received": "WORKER_PLAN_REPAIR_RESPONSE_RECEIVED",
            "repair_candidate_generated": "WORKER_PLAN_REPAIR_CANDIDATE_GENERATED",
            "repair_validation_succeeded": "WORKER_PLAN_REPAIR_SUCCEEDED",
            "repair_failed": "WORKER_PLAN_REPAIR_FAILED",
        }

        def emit_planning_event(event: str, event_payload: dict[str, Any]) -> None:
            flow_event(
                event_names.get(event, f"WORKER_PLANNING_{event.upper()}"),
                event_payload,
                run_id=run_id,
                level=(
                    "ERROR"
                    if event in {"validation_failed", "repair_failed"}
                    else "INFO"
                ),
            )

        repair_catalog = _repair_capability_catalog(cards)

        def build_repair_context(
            candidate: dict[str, Any] | None,
            error_context: dict[str, Any],
        ) -> list[dict[str, Any]]:
            del candidate, error_context
            return [
                {
                    "role": "system",
                    "content": (
                        "你只修复一个已生成的 MainAgent Worker DAG。必须返回完整 JSON，"
                        "保留合法任务和用户目标，只修改验证错误字段及必要依赖。"
                        "repair_capability_catalog 提供全部合法结构合同；不得使用固定 Worker 链路。"
                    ),
                },
                {
                    "role": "user",
                    "content": compact_json_dumps(
                        {
                            "request_mode": mode,
                            "user_request": str(query or ""),
                            "authoritative_initial_information_slots": initial_information_slots,
                            "repair_capability_catalog": repair_catalog,
                            "worker_dag_output_schema": prompt_plan_schema,
                            "planner_contract_examples": PLANNER_CONTRACT_EXAMPLES,
                        }
                    ),
                },
            ]

        semantic_payload = self.llm_service.generate_json(
            stage="graph_coordinator_planner",
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": compact_json_dumps(
                        {
                            "request_mode": mode,
                            "user_request": str(query or ""),
                            "session_context_summary": str(memory_summary or "")[:6000],
                            "resolved_focus_refs": [ref.to_dict() for ref in focus_refs],
                            "available_context_refs": [ref.to_dict() for ref in context_refs],
                            "worker_capability_catalog": cards,
                            "authoritative_initial_information_slots": initial_information_slots,
                            "worker_dag_output_schema": prompt_plan_schema,
                            "planner_contract_examples": PLANNER_CONTRACT_EXAMPLES,
                            "authoritative_runtime_values": {
                                "user_id": str(user_id or "default"),
                                "reply_language": reply_language,
                                "as_of_time": str(as_of_time or ""),
                                "runtime_binding_policy": (
                                    "fields listed in worker.runtime_bound_args are supplied by code"
                                ),
                            },
                        },
                    ),
                },
            ],
            max_output_tokens=6800,
            validator=validate,
            operation=f"graph_agent_task_plan:{mode}",
            event_callback=emit_planning_event,
            disable_thinking=False,
            repair_mode="targeted",
            repair_guidance=(
                "保持用户目标和仍然合法的任务不变，只修复校验错误指向的字段与受其影响的依赖。"
                "按目标约束正向规划，不得恢复反向递归或固定 Worker 链路。"
                "inputs 的一级键必须是所选 task_contract 声明的 semantic role；每个 role 的值才是"
                "包含 from_task_id 与 expected_output_type 的对象或对象数组。根任务必须写 inputs={}。"
                "若出现 wrap_reference_under_semantic_role，必须根据 semantic_inputs_schema 选择正确 role 包裹引用；"
                "若出现 move_to_args，把字段移到 args；若出现 omit_runtime_bound，从 args 和 inputs 删除，交由程序绑定。"
                "input_contract 输出空对象 {}，四个字段都由程序生成。"
                "不得新增用户未提供、GraphRef 未解析或上游结果未产生的证券、公告、画像、风险事实和限制。"
                "每个 expected_output.information_slots 必须是能力卡 produces_information_slots 的子集；"
                "无直接目标贡献且未被下游消费的任务必须删除。报告任务应引用终端专业结果，删除已经被终端结果消费的传递性原始输入。最终必须包含 FinalReport，并使"
                "final_planned_information_slots 精确等于初始槽位与全部任务输出槽位的并集。"
            ),
            repair_context_builder=build_repair_context,
        )
        prepared_payload, binding_audit = self._prepare_payload(
            semantic_payload,
            runtime_values=runtime_values,
            authoritative_initial_information_slots=set(initial_information_slots),
            request_mode=mode,
        )
        flow_event(
            "WORKER_PLAN_AUTHORITATIVE_ARGS_BOUND",
            {
                "binding_policy": "worker_card.authoritative_arg_bindings",
                "tasks": binding_audit.get("tasks") or [],
                "worker_nodes_changed": False,
                "semantic_edges_changed": False,
            },
            run_id=run_id,
        )
        compiled_payload = self._compile_payload(prepared_payload)
        flow_event(
            "WORKER_PLAN_DEPENDENCIES_DERIVED",
            {
                "task_count": len(compiled_payload.get("tasks") or []),
                "derivation": "inputs.from_task_id -> dependency_task_ids",
                "semantic_plan": semantic_payload,
                "compiled_plan": compiled_payload,
                "new_edges_invented": False,
            },
            run_id=run_id,
        )
        flow_event(
            "WORKER_PLAN_ACCEPTED",
            {
                "request_mode": mode,
                "goal_contract": compiled_payload.get("goal_contract") or {},
                "planning_state": compiled_payload.get("planning_state") or {},
                "task_count": len(compiled_payload.get("tasks") or []),
                "tasks": compiled_payload.get("tasks") or [],
                "dag_mutation_after_planning": "forbidden",
                "dependency_derivation": "compiled_from_semantic_inputs",
            },
            run_id=run_id,
        )

        tasks: list[GraphAgentTask] = []
        for row in compiled_payload["tasks"]:
            card = self.directory.get(str(row["worker_id"]))
            dependencies = [
                str(item) for item in row.get("dependency_task_ids") or []
            ]
            try:
                priority = max(0, min(10, int(row.get("priority", 1))))
            except (TypeError, ValueError):
                priority = 1
            tasks.append(
                GraphAgentTask(
                    task_id=str(row["task_id"]),
                    run_id=run_id,
                    session_id=session_id,
                    worker_id=card.worker_id,
                    assigned_agent=card.agent_id,
                    objective=str(row["objective"]),
                    task_type=str(row["task_type"]),
                    args=dict(row.get("args") or {}),
                    inputs=dict(row.get("inputs") or {}),
                    expected_output_type=str(row["expected_output_type"]),
                    purpose=str(row.get("purpose") or row.get("objective") or ""),
                    why_selected=str(row.get("why_selected") or ""),
                    input_contract=dict(row.get("input_contract") or {}),
                    expected_output=dict(row.get("expected_output") or {}),
                    expected_effect=dict(row.get("expected_effect") or {}),
                    completion_criteria=[
                        str(item) for item in row.get("completion_criteria") or []
                    ],
                    failure_policy=dict(row.get("failure_policy") or {}),
                    replan_triggers=[
                        str(item) for item in row.get("replan_triggers") or []
                    ],
                    user_id=user_id,
                    focus_refs=list(focus_refs),
                    context_refs=list(context_refs),
                    dependency_task_ids=dependencies,
                    required_outputs=[str(row["expected_output_type"])],
                    constraints=[
                        str(item) for item in row.get("constraints") or []
                    ],
                    as_of_time=as_of_time,
                    priority=priority,
                    status=(
                        TaskStatus.READY
                        if not dependencies
                        else TaskStatus.CREATED
                    ),
                    metadata={
                        "request_mode": mode,
                        "goal_contract": dict(
                            compiled_payload.get("goal_contract") or {}
                        ),
                        "planning_state": dict(
                            compiled_payload.get("planning_state") or {}
                        ),
                        "structured_worker_contract": True,
                        "dependency_derivation": "compiled_from_semantic_inputs",
                    },
                )
            )
        self._validate_dependencies(tasks)
        for task in tasks:
            self.directory.validate_task_contract(task)
        flow_event(
            "WORKER_DAG_VALIDATED",
            {
                "task_count": len(tasks),
                "tasks": [task.safe_for_coordinator() for task in tasks],
                "validator_action": "accept_only_no_mutation",
                "dependency_derivation": "compiled_from_semantic_inputs",
            },
            run_id=run_id,
        )
        return tasks, {
            "planner": "main_agent_worker_dag_llm",
            "request_mode": mode,
            "fallback_used": False,
            "legacy_task_plan_consumed": False,
            "tool_visibility": "none",
            "worker_selection_owner": "main_agent",
            "dag_mutation_after_planning": "forbidden",
            "dependency_derivation": "compiled_from_semantic_inputs",
            "graph_contract_version": "graph_agent_task.v2",
            "structured_worker_contract": True,
            "goal_contract": dict(compiled_payload.get("goal_contract") or {}),
            "planning_state": dict(compiled_payload.get("planning_state") or {}),
            "planning_policy": "goal_constrained_forward_planning",
            "task_expectations_generated": True,
        }

    @staticmethod
    def _task_plan_row(task: GraphAgentTask) -> dict[str, Any]:
        """Return a planner-schema row for an already executed reusable task."""

        return {
            "task_id": task.task_id,
            "worker_id": task.worker_id,
            "objective": task.objective,
            "purpose": task.purpose or task.objective,
            "why_selected": task.why_selected or "该任务结果已验证并在局部重规划中复用。",
            "task_type": task.task_type,
            "args": dict(task.args),
            "inputs": dict(task.inputs),
            "input_contract": dict(task.input_contract),
            "expected_output": dict(task.expected_output),
            "expected_effect": dict(task.expected_effect),
            "completion_criteria": list(task.completion_criteria),
            "failure_policy": dict(task.failure_policy),
            "replan_triggers": list(task.replan_triggers),
            "constraints": list(task.constraints),
            "expected_output_type": task.expected_output_type,
            "priority": task.priority,
        }

    @staticmethod
    def _frozen_task_signature(row: dict[str, Any]) -> dict[str, Any]:
        """Fields that a forward replan may not change for a reused result."""

        return {
            "task_id": str(row.get("task_id") or ""),
            "worker_id": str(row.get("worker_id") or "").upper(),
            "task_type": str(row.get("task_type") or ""),
            "args": dict(row.get("args") or {}),
            "inputs": dict(row.get("inputs") or {}),
            "expected_output_type": str(row.get("expected_output_type") or ""),
            "expected_output": dict(row.get("expected_output") or {}),
            "completion_criteria": list(row.get("completion_criteria") or []),
            "failure_policy": dict(row.get("failure_policy") or {}),
            "replan_triggers": list(row.get("replan_triggers") or []),
        }

    @staticmethod
    def _reusable_task_ids(
        tasks: list[GraphAgentTask],
        results: dict[str, GraphWorkerResult],
    ) -> list[str]:
        """Return successful non-report tasks whose dependency closure is reusable."""

        eligible: set[str] = set()
        for task in tasks:
            if task.expected_output_type == "FinalReport" or task.task_id not in results:
                continue
            result = results[task.task_id]
            if result.status not in {ResultStatus.COMPLETED, ResultStatus.PROPOSAL_READY}:
                continue
            if result.output_type != task.expected_output_type:
                continue
            metadata = dict(result.metadata or {})
            if metadata.get("coverage_satisfied") is False:
                continue
            actual_slots = metadata.get("produced_information_slots")
            if isinstance(actual_slots, list):
                expected_slots = set(
                    dict(task.expected_output or {}).get("information_slots") or []
                )
                if not expected_slots.issubset({str(item) for item in actual_slots}):
                    continue
            eligible.add(task.task_id)
        reusable: set[str] = set()
        progressed = True
        while progressed:
            progressed = False
            for task in tasks:
                if task.task_id not in eligible or task.task_id in reusable:
                    continue
                if set(task.dependency_task_ids).issubset(reusable):
                    reusable.add(task.task_id)
                    progressed = True
        return [task.task_id for task in tasks if task.task_id in reusable]

    def replan_forward(
        self,
        *,
        query: str,
        request_mode: str,
        session_id: str,
        run_id: str,
        user_id: str,
        focus_refs: list,
        context_refs: list,
        memory_summary: str,
        language: str,
        as_of_time: str,
        current_tasks: list[GraphAgentTask],
        current_results: dict[str, GraphWorkerResult],
        observations: list[dict[str, Any]],
        replan_round: int,
    ) -> tuple[list[GraphAgentTask], list[GraphAgentTask], dict[str, Any]]:
        """Create a validated forward DAG patch while freezing successful results.

        The model returns a complete active plan containing every reusable task
        unchanged plus one or more new tasks. Failed, partial, or superseded tasks
        are omitted. The coordinator executes only the new task IDs and reuses the
        frozen WorkerResults as dependency inputs.
        """

        mode = str(request_mode or "analysis").strip().lower()
        cards = planning_catalog_for_prompt(
            self.directory.planning_catalog(), request_mode=mode
        )
        prompt_plan_schema = plan_schema_for_prompt(PLAN_SCHEMA)
        flow_event(
            "LLM_PROMPT_COMPACTION_APPLIED",
            {
                "version": "v18.4",
                "stage": "graph_coordinator_forward_replan",
                "request_mode": mode,
                "worker_count": len(cards),
                "task_contract_count": sum(
                    len(item.get("task_contracts") or []) for item in cards
                ),
                "catalog_chars": len(compact_json_dumps(cards)),
                "schema_chars": len(compact_json_dumps(prompt_plan_schema)),
                "llm_decision_owner": "main_agent",
            },
            run_id=run_id,
        )
        reply_language = "en" if language == "en" else "zh"
        runtime_values = self._authoritative_runtime_values(
            focus_refs=focus_refs,
            context_refs=context_refs,
            user_id=str(user_id or "default"),
            reply_language=reply_language,
            as_of_time=str(as_of_time or ""),
            run_id=run_id,
        )
        authoritative_ref_ids = {
            str(ref.node_id) for ref in [*focus_refs, *context_refs]
        }
        original_meta = next(
            (
                dict(task.metadata or {})
                for task in current_tasks
                if isinstance(task.metadata, dict) and task.metadata.get("goal_contract")
            ),
            {},
        )
        goal_contract = dict(original_meta.get("goal_contract") or {})
        planning_state = dict(original_meta.get("planning_state") or {})
        initial_information_slots = list(
            planning_state.get("initial_available_information_slots")
            or self._initial_information_slots(
                request_mode=mode,
                focus_refs=focus_refs,
                context_refs=context_refs,
                memory_summary=memory_summary,
            )
        )
        reusable_ids = self._reusable_task_ids(current_tasks, current_results)
        task_by_id = {task.task_id: task for task in current_tasks}
        frozen_rows = [self._task_plan_row(task_by_id[task_id]) for task_id in reusable_ids]
        frozen_prompt_rows = [
            {**row, "input_contract": {}} for row in frozen_rows
        ]
        frozen_signatures = {
            str(row["task_id"]): self._frozen_task_signature(row)
            for row in frozen_rows
        }
        all_previous_ids = {task.task_id for task in current_tasks}

        def validate(payload: dict[str, Any]) -> None:
            try:
                prepared_payload, _ = self._prepare_payload(
                    payload,
                    runtime_values=runtime_values,
                    authoritative_initial_information_slots=set(initial_information_slots),
                    request_mode=mode,
                )
                if dict(prepared_payload.get("goal_contract") or {}) != goal_contract:
                    raise WorkerContractViolation(
                        "forward_replan_goal_contract_changed",
                        "$.goal_contract",
                    )
                rows_by_id = {
                    str(row.get("task_id") or ""): row
                    for row in prepared_payload.get("tasks") or []
                }
                for task_id, signature in frozen_signatures.items():
                    row = rows_by_id.get(task_id)
                    if row is None:
                        raise WorkerContractViolation(
                            "forward_replan_dropped_reusable_task",
                            "$.tasks",
                            task_id,
                        )
                    if self._frozen_task_signature(row) != signature:
                        raise WorkerContractViolation(
                            "forward_replan_modified_reusable_task",
                            f"$.tasks[{task_id}]",
                        )
                new_ids = set(rows_by_id) - set(frozen_signatures)
                if not new_ids:
                    raise WorkerContractViolation(
                        "forward_replan_added_no_task", "$.tasks"
                    )
                collisions = sorted(new_ids.intersection(all_previous_ids))
                if collisions:
                    raise WorkerContractViolation(
                        "forward_replan_reused_superseded_task_id",
                        "$.tasks",
                        ",".join(collisions),
                    )
                self._validate_payload(
                    prepared_payload,
                    request_mode=mode,
                    authoritative_ref_ids=authoritative_ref_ids,
                    authoritative_user_id=str(user_id or "default"),
                    reply_language=reply_language,
                    user_request=query,
                    authoritative_initial_information_slots=set(initial_information_slots),
                )
            except (WorkerContractViolation, KeyError) as exc:
                raise CoordinatorPlanningError(str(exc)) from exc

        event_prefix = f"WORKER_FORWARD_REPLAN_ROUND_{int(replan_round)}"

        def emit(event: str, event_payload: dict[str, Any]) -> None:
            flow_event(
                f"{event_prefix}_{event.upper()}",
                event_payload,
                run_id=run_id,
                level="ERROR" if "failed" in event else "INFO",
            )

        repair_catalog = _repair_capability_catalog(cards)

        def build_replan_repair_context(
            candidate: dict[str, Any] | None,
            error_context: dict[str, Any],
        ) -> list[dict[str, Any]]:
            del candidate, error_context
            return [
                {
                    "role": "system",
                    "content": (
                        "你只修复一个 Forward Replan active plan。保留 goal_contract 和冻结任务，"
                        "只修复验证错误字段并返回完整 JSON。不得新增固定 Worker 链路。"
                    ),
                },
                {
                    "role": "user",
                    "content": compact_json_dumps(
                        {
                            "request_mode": mode,
                            "user_request": query,
                            "goal_contract": goal_contract,
                            "authoritative_initial_information_slots": initial_information_slots,
                            "frozen_reusable_tasks": frozen_prompt_rows,
                            "previous_task_ids": sorted(all_previous_ids),
                            "repair_capability_catalog": repair_catalog,
                            "worker_dag_output_schema": prompt_plan_schema,
                            "planner_contract_examples": PLANNER_CONTRACT_EXAMPLES,
                        }
                    ),
                },
            ]

        payload = self.llm_service.generate_json(
            stage="graph_coordinator_forward_replan",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你负责执行后的目标约束正向局部重规划。不得从最终输出反向递归，"
                        "不得使用固定 Worker 链路。保留 frozen_reusable_tasks 的业务合同和已完成结果，"
                        "从 current_available_information_slots 继续向前枚举当前可执行能力，只添加能补齐"
                        "observations 中缺失信息或重新生成最终报告的最小任务。返回完整 active plan："
                        "所有 frozen_reusable_tasks 必须保留且不可修改；失败、部分完成和被替代任务不要保留；"
                        "新任务 ID 不得复用 previous_task_ids。新任务仍须生成完整 TaskExpectation。"
                        "GoalContract、初始信息槽位和副作用边界不可改变。current_available_information_slots 只用于判断"
                        "当前哪些能力可执行；planning_state 的 initial、final、unmet 字段由程序生成，LLM只输出 stop_reason。"
                        "最终必须包含新的 FinalReport 生产者。"
                        "严格输出 worker_dag_output_schema JSON。"
                    ),
                },
                {
                    "role": "user",
                    "content": compact_json_dumps(
                        {
                            "request_mode": mode,
                            "user_request": query,
                            "goal_contract": goal_contract,
                            "authoritative_initial_information_slots": initial_information_slots,
                            "current_available_information_slots": sorted(
                                {
                                    *initial_information_slots,
                                    *[
                                        slot
                                        for task_id in reusable_ids
                                        for slot in task_by_id[task_id].expected_output.get(
                                            "information_slots", []
                                        )
                                    ],
                                }
                            ),
                            "frozen_reusable_tasks": frozen_prompt_rows,
                            "reusable_results": {
                                task_id: coordinator_result_for_replan(
                                    current_results[task_id].safe_for_coordinator()
                                )
                                for task_id in reusable_ids
                            },
                            "observations": [
                                observation_for_replan(item) for item in observations
                            ],
                            "previous_task_ids": sorted(all_previous_ids),
                            "worker_capability_catalog": cards,
                            "worker_dag_output_schema": prompt_plan_schema,
                            "planner_contract_examples": PLANNER_CONTRACT_EXAMPLES,
                            "authoritative_runtime_values": {
                                "user_id": str(user_id or "default"),
                                "reply_language": reply_language,
                                "as_of_time": str(as_of_time or ""),
                            },
                        },
                    ),
                },
            ],
            max_output_tokens=6800,
            validator=validate,
            operation=f"graph_agent_forward_replan:{mode}:round_{replan_round}",
            event_callback=emit,
            disable_thinking=False,
            repair_mode="targeted",
            repair_guidance=(
                "保留 goal_contract 和 frozen_reusable_tasks；不要修改已复用任务。"
                "planning_state 的 initial/final/unmet 槽位由程序根据 authoritative_initial_information_slots 和完整 active plan 输出生成。"
                "只修复错误字段并从 current_available_information_slots 正向选择补齐缺失槽位的能力。"
                "inputs 必须使用 semantic role 包裹 typed WorkerResult reference；根任务 inputs={}。"
                "省略 input_contract.direct_arg_names 与 runtime_bound_args，由程序生成。"
                "新任务使用唯一 task_id，并重新生成可达的 FinalReport。报告格式失败时保持终端专业输入不变，禁止增加其传递性原始上游。"
            ),
            repair_context_builder=build_replan_repair_context,
        )
        prepared, binding_audit = self._prepare_payload(
            payload,
            runtime_values=runtime_values,
            authoritative_initial_information_slots=set(initial_information_slots),
            request_mode=mode,
        )
        compiled = self._compile_payload(prepared)
        tasks: list[GraphAgentTask] = []
        for row in compiled["tasks"]:
            card = self.directory.get(str(row["worker_id"]))
            dependencies = [str(item) for item in row.get("dependency_task_ids") or []]
            task = GraphAgentTask(
                task_id=str(row["task_id"]),
                run_id=run_id,
                session_id=session_id,
                worker_id=card.worker_id,
                assigned_agent=card.agent_id,
                objective=str(row["objective"]),
                purpose=str(row.get("purpose") or row.get("objective") or ""),
                why_selected=str(row.get("why_selected") or ""),
                task_type=str(row["task_type"]),
                args=dict(row.get("args") or {}),
                inputs=dict(row.get("inputs") or {}),
                input_contract=dict(row.get("input_contract") or {}),
                expected_output_type=str(row["expected_output_type"]),
                expected_output=dict(row.get("expected_output") or {}),
                expected_effect=dict(row.get("expected_effect") or {}),
                completion_criteria=[str(item) for item in row.get("completion_criteria") or []],
                failure_policy=dict(row.get("failure_policy") or {}),
                replan_triggers=[str(item) for item in row.get("replan_triggers") or []],
                user_id=user_id,
                focus_refs=list(focus_refs),
                context_refs=list(context_refs),
                dependency_task_ids=dependencies,
                required_outputs=[str(row["expected_output_type"])],
                constraints=[str(item) for item in row.get("constraints") or []],
                as_of_time=as_of_time,
                priority=max(0, min(10, int(row.get("priority", 1)))),
                status=TaskStatus.READY if not dependencies else TaskStatus.CREATED,
                metadata={
                    "request_mode": mode,
                    "goal_contract": dict(compiled.get("goal_contract") or {}),
                    "planning_state": dict(compiled.get("planning_state") or {}),
                    "structured_worker_contract": True,
                    "dependency_derivation": "compiled_from_semantic_inputs",
                    "replan_round": int(replan_round),
                },
            )
            tasks.append(task)
        self._validate_dependencies(tasks)
        for task in tasks:
            self.directory.validate_task_contract(task)
        new_tasks = [task for task in tasks if task.task_id not in set(reusable_ids)]
        return tasks, new_tasks, {
            "planner": "main_agent_forward_replan_llm",
            "replan_round": int(replan_round),
            "reused_task_ids": list(reusable_ids),
            "new_task_ids": [task.task_id for task in new_tasks],
            "binding_audit": binding_audit,
            "goal_contract": dict(compiled.get("goal_contract") or {}),
            "planning_state": dict(compiled.get("planning_state") or {}),
            "planning_policy": "goal_constrained_forward_replanning",
        }

    def _validate_payload(
        self,
        payload: dict[str, Any],
        *,
        request_mode: str,
        authoritative_ref_ids: set[str] | None = None,
        authoritative_user_id: str = "",
        reply_language: str = "zh",
        user_request: str = "",
        authoritative_initial_information_slots: set[str] | None = None,
    ) -> None:
        """Validate a goal-constrained forward plan without business-chain rules.

        Checks are generic: GoalContract consistency, authoritative initial
        information state, per-task expectations, capability slot semantics,
        request-mode and side-effect boundaries, typed upstream references,
        forward slot coverage, acyclicity, contribution, and report reachability.
        No business Worker sequence is encoded here.
        """

        del user_request  # Business intent interpretation belongs to MainAgent.
        self._validate_planner_field_placement(payload)
        validate_schema(payload, PLAN_SCHEMA)

        goal_contract = dict(payload.get("goal_contract") or {})
        desired_output_types = {
            str(item).strip()
            for item in goal_contract.get("desired_output_types") or []
            if str(item or "").strip()
        }
        goal_access_mode = str(
            goal_contract.get("access_mode") or AccessMode.READ.value
        ).strip().lower()
        if goal_access_mode not in {item.value for item in AccessMode}:
            raise WorkerContractViolation(
                "invalid_goal_access_mode",
                "$.goal_contract.access_mode",
                goal_access_mode,
            )
        # The public MainAgent planner only creates read-only analysis or
        # run-local proposal plans. Persistent writes use the explicit WRITE
        # confirmation and execution protocol.
        if request_mode in {"analysis", "proposal"} and goal_access_mode != AccessMode.READ.value:
            raise WorkerContractViolation(
                "main_planner_goal_must_be_read",
                "$.goal_contract.access_mode",
                goal_access_mode,
            )
        required_information_slots = {
            str(item).strip()
            for item in goal_contract.get("required_information_slots") or []
            if str(item or "").strip()
        }
        planning_state = dict(payload.get("planning_state") or {})
        declared_initial_slots = {
            str(item).strip()
            for item in planning_state.get("initial_available_information_slots") or []
            if str(item or "").strip()
        }
        authoritative_initial_slots = set(
            authoritative_initial_information_slots or declared_initial_slots
        )
        if declared_initial_slots != authoritative_initial_slots:
            raise WorkerContractViolation(
                "planning_initial_information_slots_mismatch",
                "$.planning_state.initial_available_information_slots",
                f"expected={sorted(authoritative_initial_slots)},actual={sorted(declared_initial_slots)}",
            )
        if planning_state.get("unmet_information_slots"):
            raise WorkerContractViolation(
                "plan_contains_unmet_information_slots",
                "$.planning_state.unmet_information_slots",
                ",".join(str(item) for item in planning_state.get("unmet_information_slots") or []),
            )

        if "FinalReport" not in desired_output_types:
            raise WorkerContractViolation(
                "goal_contract_missing_final_report",
                "$.goal_contract.desired_output_types",
                "FinalReport",
            )

        rows = payload["tasks"]
        known_ids = {str(row["task_id"]) for row in rows}
        if len(known_ids) != len(rows):
            raise WorkerContractViolation("duplicate_task_id", "$.tasks")

        cards_by_task: dict[str, Any] = {}
        contracts_by_task: dict[str, Any] = {}
        output_type_by_task: dict[str, str] = {}
        proposal_capability_selected = False
        proposal_output_types: set[str] = set()
        report_task_ids: list[str] = []

        for index, row in enumerate(rows):
            task_id = str(row["task_id"])
            worker_id = str(row["worker_id"]).upper()
            card = self.directory.get(worker_id)
            cards_by_task[task_id] = card

            objective = str(row["objective"]).strip()
            if _contains_private_implementation(objective):
                raise WorkerContractViolation(
                    "private_implementation_in_worker_objective",
                    f"$.tasks[{index}].objective",
                )

            task_type = str(row["task_type"])
            if task_type not in card.accepted_task_types:
                raise WorkerContractViolation(
                    "unsupported_task_type_for_worker",
                    f"$.tasks[{index}].task_type",
                    f"{card.worker_id}:{task_type}",
                )
            contract = card.task_contract(task_type)
            contracts_by_task[task_id] = contract
            if contract.allowed_request_modes and request_mode not in set(
                contract.allowed_request_modes
            ):
                raise WorkerContractViolation(
                    "task_not_allowed_in_request_mode",
                    f"$.tasks[{index}].task_type",
                    f"task_type={task_type},mode={request_mode},allowed={contract.allowed_request_modes}",
                )

            expected_output = dict(row.get("expected_output") or {})
            expectation_type = str(expected_output.get("output_type") or "")
            if expectation_type != str(row.get("expected_output_type") or ""):
                raise WorkerContractViolation(
                    "task_expectation_output_type_mismatch",
                    f"$.tasks[{index}].expected_output.output_type",
                    f"expected_output_type={row.get('expected_output_type')},actual={expectation_type}",
                )
            expected_slots = {
                str(item).strip()
                for item in expected_output.get("information_slots") or []
                if str(item or "").strip()
            }
            capability_slots = set(contract.produces_information_slots)
            unsupported_slots = sorted(expected_slots - capability_slots)
            if unsupported_slots:
                raise WorkerContractViolation(
                    "task_expectation_exceeds_capability_slots",
                    f"$.tasks[{index}].expected_output.information_slots",
                    f"task_type={task_type},unsupported={unsupported_slots},capability={sorted(capability_slots)}",
                )
            input_contract = dict(row.get("input_contract") or {})
            declared_runtime_args = set(input_contract.get("runtime_bound_args") or [])
            contract_runtime_args = set(contract.authoritative_arg_bindings)
            if declared_runtime_args != contract_runtime_args:
                raise WorkerContractViolation(
                    "task_expectation_runtime_args_mismatch",
                    f"$.tasks[{index}].input_contract.runtime_bound_args",
                    f"expected={sorted(contract_runtime_args)},actual={sorted(declared_runtime_args)}",
                )
            direct_arg_names = set(input_contract.get("direct_arg_names") or [])
            actual_arg_names = set(dict(row.get("args") or {})) - contract_runtime_args
            if direct_arg_names != actual_arg_names:
                raise WorkerContractViolation(
                    "task_expectation_direct_args_mismatch",
                    f"$.tasks[{index}].input_contract.direct_arg_names",
                    f"expected={sorted(actual_arg_names)},actual={sorted(direct_arg_names)}",
                )
            completion_criteria = [
                str(item).strip() for item in row.get("completion_criteria") or []
                if str(item or "").strip()
            ]
            if not completion_criteria:
                raise WorkerContractViolation(
                    "task_expectation_missing_completion_criteria",
                    f"$.tasks[{index}].completion_criteria",
                )
            expected_effect = dict(row.get("expected_effect") or {})
            effect_slots = set(expected_effect.get("goal_slots_satisfied") or [])
            if not effect_slots.issubset(expected_slots):
                raise WorkerContractViolation(
                    "task_effect_slots_not_in_expected_output",
                    f"$.tasks[{index}].expected_effect.goal_slots_satisfied",
                    f"effect={sorted(effect_slots)},expected_output={sorted(expected_slots)}",
                )

            self.directory.validate_task_args(
                card.worker_id, row["args"], task_type=task_type
            )
            args = dict(row.get("args") or {})
            for arg_name, arg_value in args.items():
                if "task_id" in str(arg_name).lower():
                    raise WorkerContractViolation(
                        "task_reference_not_allowed_in_args",
                        f"$.tasks[{index}].args.{arg_name}",
                    )
                if not arg_name.endswith("_ref_ids") or not isinstance(arg_value, list):
                    continue
                unknown_refs = [
                    str(item)
                    for item in arg_value
                    if str(item) not in set(authoritative_ref_ids or set())
                ]
                if unknown_refs:
                    raise WorkerContractViolation(
                        "worker_arg_ref_not_in_authoritative_context",
                        f"$.tasks[{index}].args.{arg_name}",
                        ",".join(unknown_refs[:20]),
                    )
            if "user_id" in args and str(args.get("user_id")) != authoritative_user_id:
                raise WorkerContractViolation(
                    "worker_arg_user_id_mismatch",
                    f"$.tasks[{index}].args.user_id",
                )
            if "reply_language" in args and str(args.get("reply_language")) != reply_language:
                raise WorkerContractViolation(
                    "worker_arg_reply_language_mismatch",
                    f"$.tasks[{index}].args.reply_language",
                )

            output_type = str(row["expected_output_type"])
            if contract.output_type and output_type != contract.output_type:
                raise WorkerContractViolation(
                    "task_contract_output_type_mismatch",
                    f"$.tasks[{index}].expected_output_type",
                    f"task_type={task_type},expected={contract.output_type},actual={output_type}",
                )
            if output_type not in card.output_types:
                raise WorkerContractViolation(
                    "unexpected_task_output_type",
                    f"$.tasks[{index}].expected_output_type",
                    f"{card.worker_id}:{output_type}",
                )
            output_type_by_task[task_id] = output_type

            task_access_mode = AccessMode.from_value(
                getattr(contract, "access_mode", AccessMode.READ.value)
                or AccessMode.READ.value
            ).value
            if task_access_mode not in {item.value for item in AccessMode}:
                raise WorkerContractViolation(
                    "invalid_worker_access_mode",
                    f"$.tasks[{index}].worker_id",
                    task_access_mode,
                )
            if task_access_mode == AccessMode.WRITE.value and goal_access_mode != AccessMode.WRITE.value:
                raise WorkerContractViolation(
                    "write_worker_not_allowed_by_goal",
                    f"$.tasks[{index}].worker_id",
                    card.worker_id,
                )
            # Proposal is a semantic product, not a persistent write. It remains
            # available only when MainAgent classified the request as proposal.
            if card.can_generate_proposal:
                proposal_capability_selected = True
                proposal_output_types.add(output_type)
                if request_mode != "proposal":
                    raise WorkerContractViolation(
                        "proposal_capability_not_allowed_in_request_mode",
                        f"$.tasks[{index}].worker_id",
                        card.worker_id,
                    )
            if output_type == "FinalReport":
                report_task_ids.append(task_id)

        present_output_types = set(output_type_by_task.values())
        missing_goal_outputs = sorted(desired_output_types - present_output_types)
        if missing_goal_outputs:
            raise WorkerContractViolation(
                "goal_output_not_produced",
                "$.goal_contract.desired_output_types",
                "missing=" + ",".join(missing_goal_outputs),
            )
        if not report_task_ids:
            raise WorkerContractViolation(
                "plan_missing_final_report_worker",
                "$.tasks",
            )
        if request_mode == "proposal":
            if not proposal_capability_selected:
                raise WorkerContractViolation(
                    "proposal_plan_missing_proposal_capability",
                    "$.tasks",
                )
            if not desired_output_types.intersection(proposal_output_types):
                raise WorkerContractViolation(
                    "goal_contract_missing_proposal_output",
                    "$.goal_contract.desired_output_types",
                    "include the selected proposal capability output type",
                )
        elif proposal_capability_selected:
            raise WorkerContractViolation(
                "analysis_plan_contains_proposal_capability",
                "$.tasks",
            )

        compiled_rows: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            task_id = str(row["task_id"])
            card = cards_by_task[task_id]
            contract = contracts_by_task[task_id]
            inputs = self._canonical_inputs(row.get("inputs") or {})
            dependencies = self.directory.validate_task_inputs(
                card.worker_id,
                inputs,
                task_type=str(row.get("task_type") or ""),
                task_id=task_id,
                output_type_by_task=output_type_by_task,
                path=f"$.tasks[{index}].inputs",
            )
            validate_dependency_ids(
                dependencies,
                known_task_ids=known_ids,
                task_id=task_id,
            )
            upstream_types = {
                output_type_by_task[dependency_id]
                for dependency_id in dependencies
            }
            for group in contract.required_upstream_output_groups:
                if not upstream_types.intersection(set(group)):
                    raise WorkerContractViolation(
                        "worker_upstream_output_contract_unsatisfied",
                        f"$.tasks[{index}].inputs",
                        f"worker={card.worker_id},task_type={row.get('task_type')},"
                        f"required_one_of={group},available={sorted(upstream_types)}",
                    )
            compiled = dict(row)
            compiled["inputs"] = inputs
            compiled["dependency_task_ids"] = dependencies
            compiled_rows.append(compiled)

        self._validate_payload_dependencies(compiled_rows)
        self._validate_forward_information_state(
            compiled_rows,
            contracts_by_task=contracts_by_task,
            initial_information_slots=declared_initial_slots,
            required_information_slots=required_information_slots,
            declared_final_information_slots={
                str(item).strip()
                for item in planning_state.get("final_planned_information_slots") or []
                if str(item or "").strip()
            },
        )
        self._validate_report_reachability(compiled_rows, report_task_ids)

    @staticmethod
    def _validate_forward_information_state(
        rows: list[dict[str, Any]],
        *,
        contracts_by_task: dict[str, Any],
        initial_information_slots: set[str],
        required_information_slots: set[str],
        declared_final_information_slots: set[str],
    ) -> None:
        """Simulate the virtual information state used by forward planning."""

        by_id = {str(row["task_id"]): row for row in rows}
        available = set(initial_information_slots)
        completed: set[str] = set()
        remaining = set(by_id)
        while remaining:
            progressed = False
            for task_id in list(remaining):
                row = by_id[task_id]
                dependencies = set(row.get("dependency_task_ids") or [])
                if not dependencies.issubset(completed):
                    continue
                contract = contracts_by_task[task_id]
                input_contract = dict(row.get("input_contract") or {})
                declared_context = set(input_contract.get("available_context_slots") or [])
                if not declared_context.issubset(available):
                    raise WorkerContractViolation(
                        "task_forward_context_not_available",
                        f"$.tasks[{task_id}].input_contract.available_context_slots",
                        f"missing={sorted(declared_context - available)}",
                    )
                upstream_slots = set(input_contract.get("upstream_information_slots") or [])
                producer_slots: set[str] = set()
                for dependency in dependencies:
                    producer_slots.update(
                        by_id[dependency].get("expected_output", {}).get(
                            "information_slots", []
                        )
                    )
                if not upstream_slots.issubset(producer_slots):
                    raise WorkerContractViolation(
                        "task_forward_upstream_slots_not_produced",
                        f"$.tasks[{task_id}].input_contract.upstream_information_slots",
                        f"missing={sorted(upstream_slots - producer_slots)},produced={sorted(producer_slots)}",
                    )
                expected_slots = set(
                    row.get("expected_output", {}).get("information_slots") or []
                )
                available.update(expected_slots)
                completed.add(task_id)
                remaining.remove(task_id)
                progressed = True
            if not progressed:
                raise WorkerContractViolation(
                    "forward_information_state_stalled",
                    "$.tasks",
                    ",".join(sorted(remaining)),
                )

        missing_goal_slots = sorted(required_information_slots - available)
        if missing_goal_slots:
            raise WorkerContractViolation(
                "goal_information_slot_not_produced",
                "$.goal_contract.required_information_slots",
                "missing=" + ",".join(missing_goal_slots),
            )
        if declared_final_information_slots != available:
            raise WorkerContractViolation(
                "planning_final_information_slots_mismatch",
                "$.planning_state.final_planned_information_slots",
                f"expected={sorted(available)},actual={sorted(declared_final_information_slots)}",
            )

        consumed_by_downstream: dict[str, set[str]] = {task_id: set() for task_id in by_id}
        for row in rows:
            downstream_slots = set(
                row.get("input_contract", {}).get("upstream_information_slots") or []
            )
            for dependency in row.get("dependency_task_ids") or []:
                consumed_by_downstream.setdefault(str(dependency), set()).update(
                    downstream_slots
                )
        for task_id, row in by_id.items():
            produced = set(
                row.get("expected_output", {}).get("information_slots") or []
            )
            direct_goal = produced.intersection(required_information_slots)
            downstream_use = produced.intersection(consumed_by_downstream.get(task_id, set()))
            is_report = str(row.get("expected_output_type") or "") == "FinalReport"
            if not direct_goal and not downstream_use and not is_report:
                raise WorkerContractViolation(
                    "forward_task_has_no_goal_contribution",
                    f"$.tasks[{task_id}]",
                    f"produced={sorted(produced)}",
                )

    @staticmethod
    def _validate_payload_dependencies(rows: list[dict[str, Any]]) -> None:
        remaining = {str(row["task_id"]) for row in rows}
        completed: set[str] = set()
        while remaining:
            progressed = False
            for row in rows:
                task_id = str(row["task_id"])
                if task_id not in remaining:
                    continue
                dependencies = {
                    str(item)
                    for item in row.get("dependency_task_ids") or []
                }
                if dependencies.issubset(completed):
                    completed.add(task_id)
                    remaining.remove(task_id)
                    progressed = True
            if not progressed:
                raise WorkerContractViolation(
                    "worker_dag_cycle",
                    "$.tasks",
                    ",".join(sorted(remaining)),
                )

    @staticmethod
    def _validate_report_reachability(
        rows: list[dict[str, Any]],
        report_task_ids: list[str],
    ) -> None:
        reverse: dict[str, set[str]] = {
            str(row["task_id"]): set() for row in rows
        }
        for row in rows:
            task_id = str(row["task_id"])
            for dependency in row.get("dependency_task_ids") or []:
                reverse.setdefault(str(dependency), set()).add(task_id)

        reachable_to_report: set[str] = set(report_task_ids)
        changed = True
        while changed:
            changed = False
            for source, downstream in reverse.items():
                if source in reachable_to_report:
                    continue
                if downstream.intersection(reachable_to_report):
                    reachable_to_report.add(source)
                    changed = True

        all_ids = {str(row["task_id"]) for row in rows}
        orphaned = sorted(all_ids - reachable_to_report)
        if orphaned:
            raise WorkerContractViolation(
                "worker_task_not_connected_to_final_report",
                "$.tasks",
                ",".join(orphaned),
            )

    @staticmethod
    def _validate_dependencies(tasks: list[GraphAgentTask]) -> None:
        ids = {task.task_id for task in tasks}
        remaining = set(ids)
        completed: set[str] = set()
        while remaining:
            progressed = False
            for task in tasks:
                if task.task_id not in remaining:
                    continue
                if any(dep not in ids for dep in task.dependency_task_ids):
                    raise CoordinatorPlanningError(
                        "agent_task_unknown_dependency"
                    )
                if all(dep in completed for dep in task.dependency_task_ids):
                    completed.add(task.task_id)
                    remaining.remove(task.task_id)
                    progressed = True
            if not progressed:
                raise CoordinatorPlanningError(
                    "agent_task_dependency_cycle_or_unknown_dependency"
                )
