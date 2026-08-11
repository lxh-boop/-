"""Upfront MainAgent Worker-DAG planner.

Normal execution has one bounded planning phase before any Worker executes:

1. Interpret the user request once into one canonical intent contract.
2. Load every eligible Worker's full public description.
3. Select Worker calls that explicitly cover the canonical intent needs.
4. Generate and validate the complete Worker DAG once.
5. Each selected Worker later plans its own private Tool DAG when applicable.

The raw user request is not re-interpreted by Worker selection or Worker-DAG
generation. Replan remains an exception-recovery path and reuses the original
canonical intent contract.
"""

from __future__ import annotations

from typing import Any

from core.llm import LLMService
from core.llm.prompt_compaction import compact_json_dumps

from agent.console_trace import flow_event
from agent.runtime_version import RUNTIME_VERSION
from agent.capabilities import (
    CapabilityPlanValidator,
    CapabilityRegistry,
    CapabilityTask,
    SlotBinder,
    WorkerAssignmentValidator,
)
from agent.capabilities.semantic_slots import slot_matches_patterns

from .models import GraphAgentTask, GraphWorkerResult, ResultStatus
from .worker_catalog import WorkerDescriptionCatalog
from .worker_contracts import WorkerContractViolation


class CoordinatorPlanningError(RuntimeError):
    def __init__(self, message: str, *, diagnostics: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.diagnostics = dict(diagnostics or {})


class CoordinatorPlanner:
    """Interpret intent once, then generate one complete upfront Worker DAG."""

    def __init__(
        self,
        directory: Any,
        *,
        llm_service: LLMService,
        worker_tool_directory: Any | None = None,
    ) -> None:
        self.directory = directory
        self.llm_service = llm_service
        self.registry = CapabilityRegistry()
        self.worker_catalog = WorkerDescriptionCatalog(
            directory,
            self.registry,
            worker_tool_directory=worker_tool_directory,
        )
        self.validator = CapabilityPlanValidator(self.registry, directory)
        self.slot_binder = SlotBinder()
        self.assignment_validator = WorkerAssignmentValidator(self.registry, directory)

    @staticmethod
    def _initial_slots(
        *,
        focus_refs: list[Any],
        context_refs: list[Any],
        memory_summary: str,
    ) -> set[str]:
        slots = {
            "current_user_request",
            "user_identity",
            "permission_context",
            "reply_language",
            "as_of_time",
            "runtime_context",
            "business_parameters",
        }
        all_refs = [*list(focus_refs or []), *list(context_refs or [])]
        if focus_refs:
            slots.add("authoritative_entity_refs")
        if context_refs:
            slots.add("context_entity_refs")
        source_roles = {"source", "cause", "event", "relation_source"}
        target_roles = {"target", "impact_target", "portfolio", "holding", "relation_target"}
        if any(str(getattr(ref, "role", "") or "") in source_roles for ref in all_refs):
            slots.add("source_entity_refs")
        if any(str(getattr(ref, "role", "") or "") in target_roles for ref in all_refs):
            slots.add("target_entity_refs")
        if str(memory_summary or "").strip():
            slots.add("session_summary")
        return slots

    @staticmethod
    def _normalize_need_id(index: int) -> str:
        return f"N{index:02d}"

    def _plan_intent_contract(
        self,
        *,
        query: str,
        request_mode: str,
        run_id: str,
        language: str,
        initial_slots: set[str],
        memory_summary: str,
        context_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """The only normal-path LLM stage allowed to interpret the raw request."""

        def validate(payload: dict[str, Any]) -> None:
            if not isinstance(payload, dict):
                raise WorkerContractViolation("intent_contract_not_object", "$")
            summary = str(payload.get("intent_summary") or "").strip()
            if not summary:
                raise WorkerContractViolation("intent_summary_required", "$.intent_summary")
            raw_needs = payload.get("needs")
            if not isinstance(raw_needs, list) or not raw_needs:
                raise WorkerContractViolation("intent_needs_required", "$.needs")
            for index, row in enumerate(raw_needs):
                if not isinstance(row, dict) or not str(row.get("description") or "").strip():
                    raise WorkerContractViolation("intent_need_description_required", f"$.needs[{index}]")
            effect = str(payload.get("effect_limit") or "read").lower()
            allowed = "proposal" if request_mode == "proposal" else "read"
            if effect not in {"read", "proposal"} or (allowed == "read" and effect != "read"):
                raise WorkerContractViolation("intent_effect_exceeds_request_mode", "$.effect_limit")

        payload = self.llm_service.generate_json(
            stage="upfront_user_intent_planning",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是MainAgent的唯一用户意图解释阶段。只在这里解释原始用户请求，后续Worker选择和DAG规划不得重新解释原始请求。"
                        "把用户真正希望得到的信息拆成少量、明确、可执行的needs。intent_summary里提到的每一个分析维度都必须在needs中出现；"
                        "needs中没有的维度不要写进intent_summary。不要写Worker ID、Agent ID、Tool、Capability boundary或Slot名称。"
                        "不要因为系统拥有某项能力就自动扩大需求；也不要把用户请求中实际需要的维度省略。"
                        "当前user_request是本轮业务目标的第一权威来源；context_binding是本轮对象范围与历史对象继承规则的权威约束。"
                        "session_summary只是经过入口上下文绑定策略允许进入本阶段的对话背景，不是金融实体权威来源。"
                        "当context_binding.entity_scope=portfolio且inherit_previous_focus=false时，必须保持组合级目标；"
                        "除非当前user_request本身明确点名具体证券/公司，或available_context_kinds中已有authoritative_entity_refs，"
                        "不得把历史会话中的单一证券重新加入intent_summary、needs或scope_note，也不得把组合任务收窄成单证券任务。"
                        "具体证券、公司、行业或事件只有在当前user_request明确出现，或available_context_kinds中存在authoritative_entity_refs时，"
                        "才能进入实体特定的intent_summary或needs；不得仅根据session_summary重新引入一个未绑定的历史金融对象。"
                        "effect_limit只能遵守request_mode。只输出JSON。"
                    ),
                },
                {
                    "role": "user",
                    "content": compact_json_dumps({
                        "request_mode": request_mode,
                        "reply_language": language,
                        "user_request": query,
                        "context_binding": dict(context_binding or {}),
                        "available_context_kinds": sorted(initial_slots),
                        "authoritative_entity_refs_available": "authoritative_entity_refs" in initial_slots,
                        "session_summary": str(memory_summary or "")[:1400],
                        "required_output_shape": {
                            "intent_summary": "对用户真实目标的单一权威概括",
                            "needs": [{
                                "description": "一个明确的信息/分析需求",
                                "required": True,
                            }],
                            "constraints": ["用户明确约束，没有则空数组"],
                            "scope_note": "实体/范围说明",
                            "effect_limit": "read|proposal",
                        },
                    }),
                },
            ],
            max_output_tokens=1400,
            validator=validate,
            operation=f"upfront_intent_plan:{request_mode}",
            disable_thinking=False,
            repair_mode="targeted",
            repair_guidance="只修复意图合同结构、need描述、effect_limit；不得加入Worker、Tool、Slot或Capability名称。",
        )
        normalized_needs: list[dict[str, Any]] = []
        for index, raw in enumerate(payload.get("needs") or [], start=1):
            row = dict(raw or {})
            normalized_needs.append({
                "need_id": self._normalize_need_id(index),
                "kind": str(row.get("kind") or "business").strip() or "business",
                "description": str(row.get("description") or "").strip(),
                "required": bool(row.get("required", True)),
            })
        # A user-facing response is a runtime-level terminal requirement, not a
        # business routing rule. The producer is still selected from descriptions.
        normalized_needs.append({
            "need_id": "N_FINAL",
            "kind": "presentation",
            "description": "将本轮已验证的终端结构化结果转换为面向用户的自然语言回答，不新增业务事实或判断。",
            "required": True,
        })
        intent = {
            "schema_version": "canonical_intent_contract.v1",
            "intent_summary": str(payload.get("intent_summary") or "").strip(),
            "needs": normalized_needs,
            "constraints": [str(item).strip() for item in payload.get("constraints") or [] if str(item).strip()],
            "scope_note": str(payload.get("scope_note") or "").strip(),
            "effect_limit": str(payload.get("effect_limit") or ("proposal" if request_mode == "proposal" else "read")).lower(),
            "requires_user_facing_response": True,
        }
        flow_event(
            "CANONICAL_INTENT_CONTRACT_CREATED",
            {
                "intent_summary": intent["intent_summary"],
                "need_count": len(intent["needs"]),
                "needs": intent["needs"],
                "effect_limit": intent["effect_limit"],
                "raw_request_reinterpretation_allowed_downstream": False,
            },
            run_id=run_id,
        )
        return intent

    def _load_worker_descriptions(self, *, request_mode: str, run_id: str) -> list[dict[str, Any]]:
        descriptions = self.worker_catalog.descriptions(request_mode=request_mode)
        if not descriptions:
            raise WorkerContractViolation("worker_description_catalog_empty", "$.worker_descriptions")
        flow_event(
            "WORKER_DESCRIPTION_CATALOG_LOADED",
            {
                "worker_count": len(descriptions),
                "worker_ids": [row["worker_id"] for row in descriptions],
                "visibility": "all_public_descriptions_upfront",
                "private_tool_visibility": "none",
            },
            run_id=run_id,
        )
        return descriptions

    @staticmethod
    def _worker_output_patterns(worker: dict[str, Any]) -> list[str]:
        direct = [
            str(pattern)
            for pattern in worker.get("produced_output_patterns") or []
            if str(pattern)
        ]
        if direct:
            return list(dict.fromkeys(direct))
        # Compatibility for older tests/snapshots. The active MainAgent catalog
        # no longer exposes fine-grained boundaries.
        return list(dict.fromkeys(
            str(pattern)
            for boundary in worker.get("supported_boundaries") or []
            for pattern in boundary.get("produced_output_patterns") or []
            if str(pattern)
        ))

    @classmethod
    def _worker_supports_output(cls, worker: dict[str, Any], slot_id: str) -> bool:
        if not slot_matches_patterns(slot_id, cls._worker_output_patterns(worker)):
            return False
        if str(worker.get("output_publication_mode") or "worker_synthesized") == "private_tool_passthrough":
            discoverable = {
                str(item)
                for item in worker.get("private_tool_semantic_outputs") or []
                if str(item)
            }
            return slot_id in discoverable
        return True

    @classmethod
    def _worker_output_contract_error_detail(
        cls,
        worker: dict[str, Any],
        invalid_slots: set[str] | list[str],
    ) -> str:
        """Return repair-ready details without closing the open Slot namespace.

        Worker-synthesized Slot ids remain open-ended.  The hard boundary is the
        Worker's declared ``produced_output_patterns`` namespace.  Keeping this
        detail machine-readable lets the existing single targeted-repair call
        rename an invalid semantic key instead of merely repairing JSON shape.
        """

        mode = str(worker.get("output_publication_mode") or "worker_synthesized")
        detail: dict[str, Any] = {
            "worker_id": str(worker.get("worker_id") or ""),
            "invalid_slots": sorted({str(item) for item in invalid_slots if str(item)}),
            "output_publication_mode": mode,
            "produced_output_patterns": cls._worker_output_patterns(worker),
            "output_slot_examples": [
                str(item)
                for item in worker.get("output_slot_examples") or []
                if str(item)
            ],
        }
        if mode == "private_tool_passthrough":
            detail["private_tool_semantic_outputs"] = [
                str(item)
                for item in worker.get("private_tool_semantic_outputs") or []
                if str(item)
            ]
            detail["repair_rule"] = (
                "Select an existing private_tool_semantic_outputs key; do not synthesize a new Slot id."
            )
        else:
            detail["repair_rule"] = (
                "Reuse an output_slot_examples key when suitable, otherwise rename/create a semantic Slot key "
                "that literally matches at least one produced_output_patterns entry."
            )
        return compact_json_dumps(detail)

    @staticmethod
    def _lift_worker_call_shape_echo(payload: dict[str, Any]) -> None:
        """Normalize the model echoing the prompt's shape example as a wrapper.

        This is structural-only normalization: it does not add, remove, rename,
        or reinterpret any Worker or Slot.  It prevents the single repair budget
        from being spent only on removing ``required_output_shape`` before the
        real semantic contract error can be surfaced.
        """

        if isinstance(payload.get("worker_calls"), list):
            return
        echoed = payload.get("required_output_shape")
        if not isinstance(echoed, dict) or not isinstance(echoed.get("worker_calls"), list):
            return
        payload["worker_calls"] = echoed["worker_calls"]
        if not str(payload.get("selection_reason") or "").strip():
            payload["selection_reason"] = str(echoed.get("selection_reason") or "").strip()

    def _select_worker_calls(
        self,
        *,
        intent_contract: dict[str, Any],
        worker_descriptions: list[dict[str, Any]],
        request_mode: str,
        run_id: str,
        initial_slots: set[str],
        recovery_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Select Worker calls only from the canonical intent + public descriptions."""

        worker_by_id = {str(row["worker_id"]): row for row in worker_descriptions}
        required_need_ids = {
            str(row["need_id"])
            for row in intent_contract.get("needs") or []
            if bool(row.get("required", True))
        }

        def validate(payload: dict[str, Any]) -> None:
            self._lift_worker_call_shape_echo(payload)
            calls = payload.get("worker_calls")
            if not isinstance(calls, list) or not calls:
                raise WorkerContractViolation("worker_calls_required", "$.worker_calls")
            covered: set[str] = set()
            seen_call_ids: set[str] = set()
            for index, raw in enumerate(calls):
                if not isinstance(raw, dict):
                    raise WorkerContractViolation("worker_call_not_object", f"$.worker_calls[{index}]")
                worker_id = str(raw.get("worker_id") or "").strip().upper()
                if worker_id not in worker_by_id:
                    raise WorkerContractViolation("unknown_worker_call", f"$.worker_calls[{index}].worker_id", worker_id)
                call_id = str(raw.get("call_id") or f"WC{index+1:02d}").strip()
                if call_id in seen_call_ids:
                    raise WorkerContractViolation("duplicate_worker_call_id", "$.worker_calls")
                seen_call_ids.add(call_id)
                need_ids = {str(item) for item in raw.get("covers_need_ids") or [] if str(item)}
                unknown_needs = need_ids - {str(row["need_id"]) for row in intent_contract.get("needs") or []}
                if unknown_needs:
                    raise WorkerContractViolation("worker_call_unknown_need", f"$.worker_calls[{index}].covers_need_ids", ",".join(sorted(unknown_needs)))
                covered.update(need_ids)
                desired_slots = {str(item) for item in raw.get("desired_output_slots") or [] if str(item)}
                if not desired_slots:
                    raise WorkerContractViolation("worker_call_output_slots_required", f"$.worker_calls[{index}].desired_output_slots")
                unsupported = {
                    slot for slot in desired_slots
                    if not self._worker_supports_output(worker_by_id[worker_id], slot)
                }
                if unsupported:
                    raise WorkerContractViolation(
                        "worker_call_output_outside_worker",
                        f"$.worker_calls[{index}].desired_output_slots",
                        self._worker_output_contract_error_detail(worker_by_id[worker_id], unsupported),
                    )
            if intent_contract.get("requires_user_facing_response") and not any(
                "user_facing_report" in {str(item) for item in raw.get("desired_output_slots") or []}
                for raw in calls if isinstance(raw, dict)
            ):
                raise WorkerContractViolation("terminal_user_facing_report_uncovered", "$.worker_calls")
            missing_needs = sorted(required_need_ids - covered)
            if missing_needs:
                raise WorkerContractViolation("required_intent_need_uncovered", "$.worker_calls", ",".join(missing_needs))

        user_payload: dict[str, Any] = {
            "canonical_intent_contract": intent_contract,
            "available_initial_information_slots": sorted(initial_slots),
            "worker_descriptions": worker_descriptions,
            "required_output_shape": {
                "worker_calls": [{
                    "call_id": "WC01",
                    "worker_id": "Wxx from worker_descriptions",
                    "objective": "该Worker在本轮承担的业务目标",
                    "covers_need_ids": ["N01"],
                    "desired_output_slots": ["符合该Worker produced_output_patterns 的稳定语义Slot；已有能力优先复用output_slot_examples"],
                }],
                "selection_reason": "只解释canonical intent如何被这些Worker覆盖",
            },
        }
        if recovery_context:
            user_payload["bounded_recovery_context"] = recovery_context
        payload = self.llm_service.generate_json(
            stage="upfront_worker_call_selection" if not recovery_context else "recovery_worker_call_selection",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是MainAgent的Worker委派阶段。原始用户请求已经被唯一解释为canonical_intent_contract；禁止重新解释、扩大或缩小它。"
                        "你现在一次性看到所有可用Worker的完整公开description。每个Worker是一块完整的专业能力范围，不是一组需要你继续挑选的子能力。"
                        "使用delegation_description、delegate_when、produced_output_patterns、output_slot_examples、output_publication_mode和private_tool_semantic_outputs判断应该委派给谁。private_tool_semantic_outputs只公开该Worker可确定性产出的语义Slot，不暴露Tool身份或参数。"
                        "produced_output_patterns是硬命名合同，不是主题提示。output_publication_mode=worker_synthesized时允许创建新Slot，但每个新Key必须字面匹配至少一个produced_output_patterns：例如risk.*只能生成risk.xxx，analysis.risk*只能生成analysis.risk开头的Key；不能改写成concentration_risk_fragment这类命名。没有通配符的pattern只能原样使用。已有能力优先复用output_slot_examples。private_tool_passthrough仍只能从private_tool_semantic_outputs选择。"
                        "required_output_shape只是格式示意，不得把它作为返回包装层；顶层必须直接返回worker_calls和selection_reason。"
                        "选择能够覆盖全部required need的最小充分Worker调用集合。每个required need必须由covers_need_ids显式覆盖。"
                        "需要自然语言最终交付的presentation need必须由能真实产出user_facing_report的Worker覆盖，但不要根据Worker编号硬编码。"
                        "不要选择Tool，不要生成DAG，不要输出私有Prompt。只输出JSON。"
                    ),
                },
                {"role": "user", "content": compact_json_dumps(user_payload)},
            ],
            max_output_tokens=1800,
            validator=validate,
            operation=f"upfront_worker_calls:{request_mode}",
            disable_thinking=False,
            repair_mode="targeted",
            repair_guidance=(
                "只修复need覆盖、Worker公开产出Slot和Worker ID；不得重新解释用户请求。"
                "若validation_error.contract_code=worker_call_output_outside_worker，必须读取validation_error.detail中的"
                "worker_id、invalid_slots、produced_output_patterns、output_slot_examples和output_publication_mode："
                "worker_synthesized可在pattern命名空间内重新命名/创建Key；private_tool_passthrough只能选择private_tool_semantic_outputs；"
                "不得原样保留不匹配pattern的Slot。"
            ),
        )
        calls: list[dict[str, Any]] = []
        for index, raw in enumerate(payload.get("worker_calls") or [], start=1):
            row = dict(raw or {})
            calls.append({
                "call_id": f"WC{index:02d}",
                "worker_id": str(row.get("worker_id") or "").strip().upper(),
                "objective": str(row.get("objective") or "").strip(),
                "covers_need_ids": list(dict.fromkeys(str(item) for item in row.get("covers_need_ids") or [] if str(item))),
                "desired_output_slots": list(dict.fromkeys(str(item) for item in row.get("desired_output_slots") or [] if str(item))),
            })
        normalized = {"worker_calls": calls, "selection_reason": str(payload.get("selection_reason") or "").strip()}
        validate(normalized)
        flow_event(
            "UPFRONT_WORKER_CALLS_SELECTED",
            {
                "worker_call_count": len(calls),
                "worker_ids": [row["worker_id"] for row in calls],
                "need_coverage": {row["call_id"]: row["covers_need_ids"] for row in calls},
                "selection_reason": normalized["selection_reason"][:1200],
                "raw_request_used": False,
            },
            run_id=run_id,
        )
        return normalized

    def _normalize_task_ids(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for task_index, raw_task in enumerate(tasks or [], start=1):
            if not isinstance(raw_task, dict):
                continue
            task_id = f"T{task_index:02d}"
            row = dict(raw_task)
            row["task_id"] = task_id
            row["worker_id"] = str(row.get("worker_id") or "").strip().upper()
            # ``boundary_id`` is retained only as a compatibility/audit field.
            # MainAgent no longer selects a fine-grained sub-boundary. Runtime
            # deterministically labels the task with the selected Worker's
            # existing role, while contract validation uses that Worker's full
            # capability scope.
            try:
                row["boundary_id"] = str(self.directory.get(row["worker_id"]).role)
            except Exception:
                row["boundary_id"] = ""
            contracts: list[dict[str, Any]] = []
            for contract_index, raw_contract in enumerate(row.get("contracts") or [], start=1):
                if not isinstance(raw_contract, dict):
                    continue
                contract = dict(raw_contract)
                contract["contract_id"] = f"{task_id}-C{contract_index:02d}"
                contract.setdefault("description", str(row.get("objective") or ""))
                contract.setdefault("criticality", "required")
                contract.setdefault("effect_limit", row.get("effect_limit") or "read")
                contract.setdefault("allowed_terminal_states", ["completed", "business_empty", "business_insufficient"])
                contracts.append(contract)
            row["contracts"] = contracts
            normalized.append(row)
        return normalized

    def _goal_contract(
        self,
        *,
        intent_contract: dict[str, Any],
        worker_calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        desired_slots = list(dict.fromkeys(
            slot
            for call in worker_calls
            for slot in call.get("desired_output_slots") or []
            if str(slot)
        ))
        if intent_contract.get("requires_user_facing_response") and "user_facing_report" not in desired_slots:
            desired_slots.append("user_facing_report")
        return {
            "goal_summary": str(intent_contract.get("intent_summary") or "").strip(),
            "desired_outputs": desired_slots,
            "required_information_slots": ["user_facing_report"] if intent_contract.get("requires_user_facing_response") else [],
            "effect_limit": str(intent_contract.get("effect_limit") or "read"),
            "intent_need_ids": [str(row.get("need_id")) for row in intent_contract.get("needs") or [] if row.get("need_id")],
        }

    def _generate_worker_dag(
        self,
        *,
        intent_contract: dict[str, Any],
        worker_call_plan: dict[str, Any],
        worker_descriptions: list[dict[str, Any]],
        request_mode: str,
        run_id: str,
        initial_slots: set[str],
        recovery_context: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], list[CapabilityTask]]:
        calls = list(worker_call_plan.get("worker_calls") or [])
        selected_ids = {str(row.get("worker_id") or "") for row in calls}
        selected_details = [row for row in worker_descriptions if row.get("worker_id") in selected_ids]
        selected_by_id = {str(row.get("worker_id") or ""): row for row in selected_details}
        goal = self._goal_contract(intent_contract=intent_contract, worker_calls=calls)

        def validate(candidate: dict[str, Any]) -> None:
            raw_tasks = candidate.get("tasks")
            if not isinstance(raw_tasks, list) or not raw_tasks:
                raise WorkerContractViolation("worker_dag_tasks_required", "$.tasks")
            normalized_tasks = self._normalize_task_ids(raw_tasks)
            payload = {"goal_contract": goal, "tasks": normalized_tasks}
            tasks = self.validator.validate(payload, request_mode=request_mode, initial_information_slots=set(initial_slots))
            unknown = sorted({task.worker_id for task in tasks} - selected_ids)
            if unknown:
                raise WorkerContractViolation("worker_dag_outside_selected_calls", "$.tasks[*].worker_id", ",".join(unknown))
            # Every WorkerCall must be realized by same-worker task output coverage.
            for call in calls:
                desired = set(call.get("desired_output_slots") or [])
                produced = {
                    slot
                    for task in tasks if task.worker_id == call.get("worker_id")
                    for slot in task.output_slots()
                }
                missing = sorted(desired - produced)
                if missing:
                    raise WorkerContractViolation(
                        "worker_call_not_realized_by_dag",
                        "$.tasks",
                        f"{call.get('call_id')}:{','.join(missing)}",
                    )
            # Every promised output must be legal for the selected Worker's
            # overall scope. Passthrough Workers remain additionally restricted
            # to explicit ToolOutputContract semantic slots.
            for task in tasks:
                worker = selected_by_id.get(task.worker_id) or {}
                unsupported = sorted(
                    slot for slot in task.output_slots()
                    if not self._worker_supports_output(worker, slot)
                )
                if unsupported:
                    raise WorkerContractViolation(
                        "worker_task_output_outside_worker_scope",
                        "$.tasks",
                        self._worker_output_contract_error_detail(worker, unsupported),
                    )

        user_payload: dict[str, Any] = {
            "canonical_intent_contract": intent_contract,
            "selected_worker_calls": calls,
            "selected_worker_descriptions": selected_details,
            "available_initial_information_slots": sorted(initial_slots),
            "program_owned_goal_contract": goal,
            "required_output_shape": {
                "tasks": [{
                    "worker_id": "must appear in selected_worker_calls",
                    "objective": "short objective constrained by the WorkerCall",
                    "effect_limit": "read|proposal",
                    "priority": 1,
                    "business_parameters": {},
                    "contracts": [{
                        "description": "short obligation",
                        "required_inputs": [{"slot_id": "runtime semantic slot key", "required": True, "cardinality": "one|many", "required_paths": ["optional minimal.path", "records[*].field"]}],
                        "promised_outputs": [{"slot_id": "runtime semantic slot key", "provenance_required": True, "required_paths": []}],
                        "acceptance_rule_ids": ["registered rule id"],
                        "forbidden_output_slots": [],
                        "criticality": "required|optional",
                        "effect_limit": "read|proposal",
                    }],
                }]
            },
        }
        if recovery_context:
            user_payload["bounded_recovery_context"] = recovery_context
        payload = self.llm_service.generate_json(
            stage="upfront_worker_dag_planning" if not recovery_context else "recovery_worker_dag_planning",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是MainAgent的Worker DAG生成阶段。canonical_intent_contract和selected_worker_calls已经是权威决定；"
                        "禁止重新解释原始用户请求，禁止增删WorkerCall。每个selected Worker代表一块完整专业能力范围，不要再为Worker选择或发明子Boundary。"
                        "一次性生成完整Worker DAG的任务/CapabilityContract；只描述Worker之间实际需要传递的信息Slot和本任务承诺产出的信息Slot。"
                        "每个WorkerCall的desired_output_slots必须由同一worker_id的任务真实承诺产出；Slot是开放的运行时语义Key，不是固定业务枚举。output_publication_mode=private_tool_passthrough时，desired_output_slots必须从private_tool_semantic_outputs选择；新增Tool的OutputContract会自动进入该列表，不需要中央Slot注册。output_publication_mode=worker_synthesized时，可创建新语义Key，但Key必须字面匹配该Worker整体produced_output_patterns；produced_output_patterns是硬命名空间合同，不是语义提示。已有Key优先复用output_slot_examples。生产者/消费者合同必须使用完全相同的Key。依赖关系不要手写，Runtime会根据Slot生产/消费自动推导。"
                        "session_summary、current_user_request、reply_language、runtime_context属于规划/运行上下文，不是经过验证的业务事实Slot，除系统诊断Worker外不要把它们声明成业务required_inputs。"
                        "不要输出boundary_id、goal_contract（它由程序从canonical intent和WorkerCall固定生成），不要输出Tool、私有Prompt、dependency_task_ids、GraphRef、模型、超时、重试。"
                        "合同required_inputs只声明该任务实际不可缺少的输入；当你明确知道下游只需要Slot中的少数字段时，用required_paths声明最小字段路径（支持records[*].field），不知道结构时留空，禁止猜字段。只输出JSON。"
                    ),
                },
                {"role": "user", "content": compact_json_dumps(user_payload)},
            ],
            max_output_tokens=3200,
            validator=validate,
            operation=f"upfront_worker_dag:{request_mode}",
            disable_thinking=False,
            repair_mode="targeted",
            repair_guidance=(
                "只修复已选WorkerCall到Worker级CapabilityContract的实现；不得选择子Boundary、重新解释意图、增删WorkerCall或输出Tool。"
                "若validation_error.detail包含Worker输出合同，任何修复后的promised_outputs都必须严格匹配其中的produced_output_patterns；"
                "worker_synthesized允许在pattern内创建新Key，但禁止在pattern外自由命名。"
            ),
        )
        normalized_tasks = self._normalize_task_ids(payload.get("tasks") or [])
        normalized = {"goal_contract": goal, "tasks": normalized_tasks}
        tasks = self.validator.validate(normalized, request_mode=request_mode, initial_information_slots=set(initial_slots))
        validate({"tasks": normalized_tasks})
        flow_event(
            "UPFRONT_WORKER_DAG_VALIDATED",
            {
                "task_count": len(tasks),
                "contract_count": sum(len(item.contracts) for item in tasks),
                "worker_ids": [item.worker_id for item in tasks],
                "worker_scope_ids": [item.boundary_id for item in tasks],
                "main_agent_worker_visibility": "all_public_descriptions_upfront",
                "main_agent_tool_visibility": "none",
                "raw_request_used": False,
            },
            run_id=run_id,
        )
        return normalized, tasks

    def _compile(
        self,
        *,
        payload: dict[str, Any],
        tasks: list[CapabilityTask],
        request_mode: str,
        session_id: str,
        run_id: str,
        user_id: str,
        focus_refs: list[Any],
        context_refs: list[Any],
        as_of_time: str,
        initial_slots: set[str],
        planning_meta: dict[str, Any],
        external_producers: dict[str, list[dict[str, str]]] | None = None,
    ) -> tuple[list[GraphAgentTask], dict[str, Any]]:
        bindings = self.slot_binder.bind(
            tasks,
            initial_information_slots=set(initial_slots),
            external_producers=external_producers,
        )
        resolved = self.assignment_validator.validate(tasks, bindings=bindings, request_mode=request_mode)
        goal = dict(payload.get("goal_contract") or {})
        intent_contract = dict(planning_meta.get("canonical_intent_contract") or {})
        worker_calls = list((planning_meta.get("worker_call_plan") or {}).get("worker_calls") or [])
        compiled: list[GraphAgentTask] = []
        for item in resolved:
            task = item.task
            compiled.append(GraphAgentTask(
                task_id=task.task_id,
                run_id=run_id,
                session_id=session_id,
                assigned_agent=item.assigned_agent_id,
                objective=task.objective,
                user_id=user_id,
                boundary_id=task.boundary_id,
                contracts=[contract.to_dict() for contract in task.contracts],
                worker_id=item.assigned_worker_id,
                business_parameters=dict(task.business_parameters),
                resolved_input_bindings=[binding.to_dict() for binding in item.input_bindings],
                dependency_task_ids=list(item.dependency_task_ids),
                expected_output_slots=task.output_slots(),
                effect_limit=task.effect_limit,
                execution_mode=item.execution_mode,
                focus_refs=list(focus_refs),
                context_refs=list(context_refs),
                as_of_time=as_of_time,
                priority=task.priority,
                metadata={
                    "goal_contract": goal,
                    "canonical_intent_contract": intent_contract,
                    "worker_call_plan": worker_calls,
                    "worker_assignment": item.to_audit_dict(),
                    "allowed_tool_ids": list(item.allowed_tool_ids),
                    "structured_capability_contract": True,
                    "upfront_worker_dag": True,
                },
            ))
        meta = {
            "planner": "upfront_worker_dag_main_agent",
            "runtime_version": RUNTIME_VERSION,
            "planning_mode": "upfront_worker_dag_then_private_tool_dag",
            "worker_selection_owner": "main_agent",
            "capability_scope_mode": "worker_level",
            "worker_assignment_runtime_role": "validate_only",
            "raw_request_semantic_owner": "canonical_intent_contract",
            "task_count": len(compiled),
            "contract_count": sum(len(task.contracts) for task in compiled),
            "goal_contract": goal,
            "canonical_intent_contract": intent_contract,
            "worker_call_plan": planning_meta.get("worker_call_plan") or {},
            "worker_description_count": int(planning_meta.get("worker_description_count") or 0),
            "capability_plan": payload,
            "slot_binding": {
                "dependency_ids_by_task": bindings.dependency_ids_by_task,
                "producer_index": bindings.producer_index,
            },
            "assignment_audit": [item.to_audit_dict() for item in resolved],
        }
        return compiled, meta

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
        context_binding: dict[str, Any] | None = None,
    ) -> tuple[list[GraphAgentTask], dict[str, Any]]:
        mode = str(request_mode or "analysis").lower()
        if mode not in {"analysis", "proposal"}:
            raise CoordinatorPlanningError(f"unsupported_agent_request_mode:{mode}")
        initial_slots = self._initial_slots(focus_refs=focus_refs, context_refs=context_refs, memory_summary=memory_summary)
        try:
            intent = self._plan_intent_contract(
                query=query,
                request_mode=mode,
                run_id=run_id,
                language=language,
                initial_slots=initial_slots,
                memory_summary=memory_summary,
                context_binding=context_binding,
            )
            descriptions = self._load_worker_descriptions(request_mode=mode, run_id=run_id)
            worker_call_plan = self._select_worker_calls(
                intent_contract=intent,
                worker_descriptions=descriptions,
                request_mode=mode,
                run_id=run_id,
                initial_slots=initial_slots,
            )
            payload, tasks = self._generate_worker_dag(
                intent_contract=intent,
                worker_call_plan=worker_call_plan,
                worker_descriptions=descriptions,
                request_mode=mode,
                run_id=run_id,
                initial_slots=initial_slots,
            )
            return self._compile(
                payload=payload,
                tasks=tasks,
                request_mode=mode,
                session_id=session_id,
                run_id=run_id,
                user_id=user_id,
                focus_refs=focus_refs,
                context_refs=context_refs,
                as_of_time=as_of_time,
                initial_slots=initial_slots,
                planning_meta={
                    "canonical_intent_contract": intent,
                    "worker_call_plan": worker_call_plan,
                    "worker_description_count": len(descriptions),
                },
            )
        except (WorkerContractViolation, KeyError, ValueError) as exc:
            raise CoordinatorPlanningError(
                str(exc), diagnostics={"failure_kind": "upfront_worker_dag_planning_failure"}
            ) from exc

    @staticmethod
    def _canonical_intent_from_tasks(current_tasks: list[GraphAgentTask]) -> dict[str, Any]:
        for task in current_tasks:
            value = dict((task.metadata or {}).get("canonical_intent_contract") or {})
            if value:
                return value
        return {}

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
        del query, language  # recovery must not reinterpret the raw request
        intent = self._canonical_intent_from_tasks(current_tasks)
        if not intent:
            raise WorkerContractViolation("replan_missing_canonical_intent", "$.task.metadata.canonical_intent_contract")

        reusable_ids = {
            task_id for task_id, result in current_results.items()
            if result.status in {ResultStatus.COMPLETED, ResultStatus.PROPOSAL_READY}
            and bool((result.completion or {}).get("expected_task_completed", True))
        }
        frozen = [task for task in current_tasks if task.task_id in reusable_ids]
        available_slots = self._initial_slots(focus_refs=focus_refs, context_refs=context_refs, memory_summary=memory_summary)
        external: dict[str, list[dict[str, str]]] = {}
        for task in frozen:
            result = current_results.get(task.task_id)
            produced = list((result.completion or {}).get("produced_information_slots") or []) if result else []
            for slot in produced:
                available_slots.add(str(slot))
                external.setdefault(str(slot), []).append({
                    "source_type": "upstream_task",
                    "producer_task_id": task.task_id,
                    "producer_contract_id": "frozen_result",
                    "schema_id": "",
                    "entity_scope": "same_as_input",
                })
        task_by_id = {task.task_id: task for task in current_tasks}
        failure_signatures = []
        for item in observations[:20]:
            if item.get("semantic_satisfied"):
                continue
            failed_task = task_by_id.get(str(item.get("task_id") or ""))
            error = item.get("worker_escalation") or item.get("error") or {}
            failure_signatures.append({
                "task_id": item.get("task_id"),
                "worker_id": item.get("worker_id"),
                "boundary_id": item.get("boundary_id"),
                "required_input_slots": sorted({
                    str(binding.get("input_slot_id") or "")
                    for binding in list(getattr(failed_task, "resolved_input_bindings", []) or [])
                    if str(binding.get("input_slot_id") or "")
                }),
                "error_id": error.get("error_id") or error.get("code"),
                "operation": error.get("operation"),
                "reason": error.get("reason") or error.get("message"),
                "missing_information_slots": item.get("missing_information_slots") or [],
            })
        recovery_context = {
            "round": int(replan_round),
            "frozen_result_slots": sorted(available_slots),
            "failure_signatures": failure_signatures,
            "instruction": "只修复失败能力，保持canonical intent不变；不得重新解释原始用户请求。",
        }
        descriptions = self._load_worker_descriptions(request_mode=request_mode, run_id=run_id)
        worker_call_plan = self._select_worker_calls(
            intent_contract=intent,
            worker_descriptions=descriptions,
            request_mode=request_mode,
            run_id=run_id,
            initial_slots=available_slots,
            recovery_context=recovery_context,
        )
        payload, capability_tasks = self._generate_worker_dag(
            intent_contract=intent,
            worker_call_plan=worker_call_plan,
            worker_descriptions=descriptions,
            request_mode=request_mode,
            run_id=run_id,
            initial_slots=available_slots,
            recovery_context=recovery_context,
        )
        prior_ids = {task.task_id for task in current_tasks}
        start = len(prior_ids) + 1
        remapped: list[CapabilityTask] = []
        for offset, task in enumerate(capability_tasks):
            new_id = f"T{start + offset:02d}"
            row = task.to_dict()
            row["task_id"] = new_id
            for index, contract in enumerate(row.get("contracts") or [], start=1):
                contract["contract_id"] = f"{new_id}-C{index:02d}"
            remapped.append(CapabilityTask.from_dict(row, task_id=new_id))
        failed_shapes = {
            (str(item.get("worker_id") or ""), str(item.get("boundary_id") or ""), tuple(item.get("required_input_slots") or []))
            for item in failure_signatures
        }
        repeated_shapes = []
        for task in remapped:
            shape = (task.worker_id, task.boundary_id, tuple(sorted(task.input_slots(required_only=True))))
            if shape in failed_shapes:
                repeated_shapes.append({"worker_id": task.worker_id, "boundary_id": task.boundary_id, "required_input_slots": list(shape[2])})
        if repeated_shapes:
            raise WorkerContractViolation("replan_repeated_failed_worker_shape", "$.tasks", str(repeated_shapes))
        payload = dict(payload)
        payload["tasks"] = [task.to_dict() for task in remapped]
        new_tasks, meta = self._compile(
            payload=payload,
            tasks=remapped,
            request_mode=request_mode,
            session_id=session_id,
            run_id=run_id,
            user_id=user_id,
            focus_refs=focus_refs,
            context_refs=context_refs,
            as_of_time=as_of_time,
            initial_slots=available_slots,
            planning_meta={
                "canonical_intent_contract": intent,
                "worker_call_plan": worker_call_plan,
                "worker_description_count": len(descriptions),
            },
            external_producers=external,
        )
        full = [*frozen, *new_tasks]
        meta.update({
            "replan_round": int(replan_round),
            "recovery_only": True,
            "canonical_intent_reused": True,
            "frozen_task_ids": [task.task_id for task in frozen],
            "new_task_ids": [task.task_id for task in new_tasks],
            "failure_signatures": failure_signatures,
        })
        return full, new_tasks, meta
