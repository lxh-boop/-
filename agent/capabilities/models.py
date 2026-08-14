from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


EffectLevel = Literal["read", "proposal", "write"]
Criticality = Literal["required", "optional"]
RequirementSourcePolicy = Literal["system", "user", "either"]
SatisfactionRule = Literal["exists", "non_empty", "one_of"]
ContractTerminalState = Literal[
    "completed",
    "business_empty",
    "business_insufficient",
    "need_context",
    "blocked",
    "failed",
]


@dataclass(frozen=True)
class NeedRequirement:
    """One canonical semantic requirement compiled from a user Need.

    This is planning IR, not a Worker contract. ``semantic_key`` must resolve
    through CapabilityRegistry. Runtime-owned slot/parameter semantics are
    expanded later; the LLM is not allowed to invent concrete contract policy.
    """

    requirement_id: str
    semantic_key: str
    direction: Literal["input", "output", "parameter"]
    required: bool = True
    required_paths: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "NeedRequirement":
        row = dict(value or {})
        direction = str(row.get("direction") or "input").strip().lower()
        if direction not in {"input", "output", "parameter"}:
            direction = "input"
        return cls(
            requirement_id=str(row.get("requirement_id") or "").strip(),
            semantic_key=str(row.get("semantic_key") or "").strip(),
            direction=direction,
            required=bool(row.get("required", True)),
            required_paths=list(dict.fromkeys(
                str(item).strip()
                for item in row.get("required_paths") or []
                if str(item).strip()
            )),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InputSlotRequirement:
    """One information slot that a capability contract must consume.

    The slot name and schema are selected from the boundary catalog.  Entity
    identity is never invented here; ``entity_scope`` refers to GraphRefs that
    were already resolved by the runtime.
    """

    slot_id: str
    schema_id: str = ""
    entity_scope: str = "focus_entities"
    required: bool = True
    cardinality: Literal["one", "many"] = "one"
    authority_policy: str = "authoritative_or_verified_upstream"
    freshness_policy: str = "request_default"
    required_paths: list[str] = field(default_factory=list)
    optional_paths: list[str] = field(default_factory=list)
    semantic_role: str = ""
    source_policy: RequirementSourcePolicy = "system"
    satisfaction_rule: SatisfactionRule = "exists"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "InputSlotRequirement":
        row = dict(value or {})
        return cls(
            slot_id=str(row.get("slot_id") or "").strip(),
            schema_id=str(row.get("schema_id") or "").strip(),
            entity_scope=str(row.get("entity_scope") or "focus_entities").strip(),
            required=bool(row.get("required", True)),
            cardinality=(
                "many" if str(row.get("cardinality") or "one").lower() == "many" else "one"
            ),
            authority_policy=str(
                row.get("authority_policy") or "authoritative_or_verified_upstream"
            ).strip(),
            freshness_policy=str(row.get("freshness_policy") or "request_default").strip(),
            required_paths=list(dict.fromkeys(
                str(item).strip()
                for item in row.get("required_paths") or []
                if str(item).strip()
            )),
            optional_paths=list(dict.fromkeys(
                str(item).strip()
                for item in row.get("optional_paths") or []
                if str(item).strip()
            )),
            semantic_role=str(row.get("semantic_role") or row.get("slot_id") or "").strip(),
            source_policy=(
                str(row.get("source_policy") or "system").strip().lower()
                if str(row.get("source_policy") or "system").strip().lower() in {"system", "user", "either"}
                else "system"
            ),
            satisfaction_rule=(
                str(row.get("satisfaction_rule") or "exists").strip().lower()
                if str(row.get("satisfaction_rule") or "exists").strip().lower() in {"exists", "non_empty", "one_of"}
                else "exists"
            ),
        )


@dataclass(frozen=True)
class BusinessParameterRequirement:
    """One business parameter required by a capability contract.

    Business parameters are intentionally separate from Worker-to-Worker Slots.
    They describe user/either-owned values such as target allocation, dates or
    preferences that cannot be safely invented by a domain Worker.
    """

    parameter_id: str
    semantic_role: str = ""
    required: bool = True
    source_policy: RequirementSourcePolicy = "user"
    satisfy_by: list[str] = field(default_factory=list)
    satisfaction_rule: SatisfactionRule = "one_of"
    description: str = ""
    expected_format: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "BusinessParameterRequirement":
        row = dict(value or {})
        parameter_id = str(row.get("parameter_id") or row.get("semantic_role") or "").strip()
        satisfy_by = list(dict.fromkeys(
            str(item).strip()
            for item in row.get("satisfy_by") or []
            if str(item).strip()
        ))
        if not satisfy_by and parameter_id:
            satisfy_by = [parameter_id]
        source_policy = str(row.get("source_policy") or "user").strip().lower()
        if source_policy not in {"system", "user", "either"}:
            source_policy = "user"
        satisfaction_rule = str(row.get("satisfaction_rule") or "one_of").strip().lower()
        if satisfaction_rule not in {"exists", "non_empty", "one_of"}:
            satisfaction_rule = "one_of"
        return cls(
            parameter_id=parameter_id,
            semantic_role=str(row.get("semantic_role") or parameter_id).strip(),
            required=bool(row.get("required", True)),
            source_policy=source_policy,
            satisfy_by=satisfy_by,
            satisfaction_rule=satisfaction_rule,
            description=str(row.get("description") or "").strip(),
            expected_format=str(row.get("expected_format") or "").strip(),
        )


@dataclass(frozen=True)
class OutputSlotGuarantee:
    """One information slot that a capability contract promises to publish."""

    slot_id: str
    schema_id: str = ""
    entity_scope: str = "same_as_input"
    provenance_required: bool = True
    authority_level: str = "worker_verified"
    freshness_policy: str = "request_default"
    required_paths: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "OutputSlotGuarantee":
        row = dict(value or {})
        return cls(
            slot_id=str(row.get("slot_id") or "").strip(),
            schema_id=str(row.get("schema_id") or "").strip(),
            entity_scope=str(row.get("entity_scope") or "same_as_input").strip(),
            provenance_required=bool(row.get("provenance_required", True)),
            authority_level=str(row.get("authority_level") or "worker_verified").strip(),
            freshness_policy=str(row.get("freshness_policy") or "request_default").strip(),
            required_paths=list(dict.fromkeys(
                str(item).strip()
                for item in row.get("required_paths") or []
                if str(item).strip()
            )),
        )


@dataclass(frozen=True)
class CapabilityContract:
    """A verifiable business obligation carried by one capability task.

    The contract says *what must be consumed, produced and verified*.  It never
    names a Worker, task type, Tool, prompt, retry policy or fixed Tool DAG.
    """

    contract_id: str
    description: str
    required_inputs: list[InputSlotRequirement] = field(default_factory=list)
    required_parameters: list[BusinessParameterRequirement] = field(default_factory=list)
    promised_outputs: list[OutputSlotGuarantee] = field(default_factory=list)
    acceptance_rule_ids: list[str] = field(default_factory=list)
    forbidden_output_slots: list[str] = field(default_factory=list)
    criticality: Criticality = "required"
    effect_limit: EffectLevel = "read"
    allowed_terminal_states: list[ContractTerminalState] = field(
        default_factory=lambda: ["completed", "business_empty", "business_insufficient"]
    )

    @classmethod
    def from_dict(
        cls,
        value: dict[str, Any],
        *,
        contract_id: str = "",
    ) -> "CapabilityContract":
        row = dict(value or {})
        return cls(
            contract_id=str(row.get("contract_id") or contract_id).strip(),
            description=str(row.get("description") or "").strip(),
            required_inputs=[
                InputSlotRequirement.from_dict(item)
                for item in row.get("required_inputs") or []
                if isinstance(item, dict)
            ],
            required_parameters=[
                BusinessParameterRequirement.from_dict(item)
                for item in row.get("required_parameters") or []
                if isinstance(item, dict)
            ],
            promised_outputs=[
                OutputSlotGuarantee.from_dict(item)
                for item in row.get("promised_outputs") or []
                if isinstance(item, dict)
            ],
            acceptance_rule_ids=list(
                dict.fromkeys(
                    str(item).strip()
                    for item in row.get("acceptance_rule_ids") or []
                    if str(item).strip()
                )
            ),
            forbidden_output_slots=list(
                dict.fromkeys(
                    str(item).strip()
                    for item in row.get("forbidden_output_slots") or []
                    if str(item).strip()
                )
            ),
            criticality=(
                "optional"
                if str(row.get("criticality") or "required").lower() == "optional"
                else "required"
            ),
            effect_limit=str(row.get("effect_limit") or "read").strip().lower(),
            allowed_terminal_states=list(
                dict.fromkeys(
                    str(item).strip()
                    for item in row.get("allowed_terminal_states")
                    or ["completed", "business_empty", "business_insufficient"]
                    if str(item).strip()
                )
            ),
        )

    def input_slots(self, *, required_only: bool = False) -> list[str]:
        return list(
            dict.fromkeys(
                item.slot_id
                for item in self.required_inputs
                if item.slot_id and (item.required or not required_only)
            )
        )

    def parameter_requirements(self, *, required_only: bool = False) -> list[BusinessParameterRequirement]:
        return [
            item for item in self.required_parameters
            if item.parameter_id and (item.required or not required_only)
        ]

    def output_slots(self) -> list[str]:
        return list(
            dict.fromkeys(item.slot_id for item in self.promised_outputs if item.slot_id)
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapabilityBoundary:
    """Stable public business capability exposed to MainAgent."""

    boundary_id: str
    name: str
    description: str
    responsibilities: list[str] = field(default_factory=list)
    non_responsibilities: list[str] = field(default_factory=list)
    accepted_input_patterns: list[str] = field(default_factory=lambda: ["*"])
    produced_output_patterns: list[str] = field(default_factory=lambda: ["*"])
    accepted_business_parameter_patterns: list[str] = field(default_factory=list)
    input_slot_examples: list[str] = field(default_factory=list)
    output_slot_examples: list[str] = field(default_factory=list)
    allowed_acceptance_rule_ids: list[str] = field(default_factory=list)
    required_context_slots: list[str] = field(default_factory=list)
    allowed_information_sources: list[str] = field(default_factory=list)
    max_effect_level: EffectLevel = "read"
    completion_principles: list[str] = field(default_factory=list)

    def safe_for_main_agent(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CapabilityTask:
    """One MainAgent-planned business capability node.

    Every task uses a contract list.  A list of length one is not a special
    execution mode.
    """

    task_id: str
    worker_id: str
    boundary_id: str
    objective: str
    contracts: list[CapabilityContract]
    business_parameters: dict[str, Any] = field(default_factory=dict)
    effect_limit: EffectLevel = "read"
    priority: int = 1

    @classmethod
    def from_dict(
        cls,
        value: dict[str, Any],
        *,
        task_id: str = "",
    ) -> "CapabilityTask":
        row = dict(value or {})
        resolved_task_id = str(row.get("task_id") or task_id).strip()
        contracts = [
            CapabilityContract.from_dict(
                item,
                contract_id=f"{resolved_task_id}-C{index:02d}" if resolved_task_id else "",
            )
            for index, item in enumerate(row.get("contracts") or [], start=1)
            if isinstance(item, dict)
        ]
        return cls(
            task_id=resolved_task_id,
            worker_id=str(row.get("worker_id") or "").strip().upper(),
            boundary_id=str(row.get("boundary_id") or "").strip(),
            objective=str(row.get("objective") or "").strip(),
            contracts=contracts,
            business_parameters=dict(row.get("business_parameters") or {}),
            effect_limit=str(row.get("effect_limit") or "read").strip().lower(),
            priority=max(0, min(10, int(row.get("priority") or 1))),
        )

    def input_slots(self, *, required_only: bool = False) -> list[str]:
        return list(
            dict.fromkeys(
                slot
                for contract in self.contracts
                for slot in contract.input_slots(required_only=required_only)
            )
        )

    def output_slots(self) -> list[str]:
        return list(
            dict.fromkeys(
                slot for contract in self.contracts for slot in contract.output_slots()
            )
        )

    def acceptance_rule_ids(self) -> list[str]:
        return list(
            dict.fromkeys(
                rule
                for contract in self.contracts
                for rule in contract.acceptance_rule_ids
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InputOutputBinding:
    source_type: Literal["runtime_context", "user_parameter", "upstream_task"]
    output_slot_id: str
    consumer_task_id: str
    consumer_contract_id: str
    input_slot_id: str
    schema_id: str = ""
    producer_task_id: str = ""
    producer_contract_id: str = ""
    entity_scope: str = ""
    required_paths: list[str] = field(default_factory=list)
    optional_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResolvedCapabilityTask:
    task: CapabilityTask
    assigned_worker_id: str
    assigned_agent_id: str
    allowed_tool_ids: list[str]
    execution_mode: str
    input_bindings: list[InputOutputBinding]
    dependency_task_ids: list[str]
    resolution_reason: str
    score: float

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task.task_id,
            "boundary_id": self.task.boundary_id,
            "assigned_worker_id": self.assigned_worker_id,
            "assigned_agent_id": self.assigned_agent_id,
            "execution_mode": self.execution_mode,
            "contract_ids": [item.contract_id for item in self.task.contracts],
            "input_bindings": [item.to_dict() for item in self.input_bindings],
            "dependency_task_ids": list(self.dependency_task_ids),
            "resolution_reason": self.resolution_reason,
            "score": float(self.score),
        }


@dataclass(frozen=True)
class ContractCompletionReport:
    contract_id: str
    status: ContractTerminalState
    satisfied_outputs: list[str] = field(default_factory=list)
    missing_outputs: list[str] = field(default_factory=list)
    failed_acceptance_rules: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
