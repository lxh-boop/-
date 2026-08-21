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

    This is planning IR.  Business data requirements resolve to simple
    Working-Memory data names; user-owned values resolve to business parameters.
    No Worker/Tool identity or transport binding appears here.
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
class DataRequirement:
    """One business-data name that may be read from the run ContextBundle.

    This is not a transport edge.  Analysis Workers receive the whole relevant
    Working-Memory view and decide whether the available data is sufficient.
    """

    name: str
    semantic_role: str = ""
    required: bool = True
    source_policy: RequirementSourcePolicy = "system"
    satisfaction_rule: SatisfactionRule = "exists"
    required_paths: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DataRequirement":
        row = dict(value or {})
        source_policy = str(row.get("source_policy") or "system").strip().lower()
        if source_policy not in {"system", "user", "either"}:
            source_policy = "system"
        satisfaction_rule = str(row.get("satisfaction_rule") or "exists").strip().lower()
        if satisfaction_rule not in {"exists", "non_empty", "one_of"}:
            satisfaction_rule = "exists"
        name = str(row.get("name") or row.get("data_name") or "").strip()
        return cls(
            name=name,
            semantic_role=str(row.get("semantic_role") or name).strip(),
            required=bool(row.get("required", True)),
            source_policy=source_policy,
            satisfaction_rule=satisfaction_rule,
            required_paths=list(dict.fromkeys(
                str(item).strip()
                for item in row.get("required_paths") or []
                if str(item).strip()
            )),
        )


@dataclass(frozen=True)
class BusinessParameterRequirement:
    """One user/either-owned business parameter that must not be invented."""

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
class DataGuarantee:
    """One simple data name a Worker promises to materialize on success."""

    name: str
    required_paths: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DataGuarantee":
        row = dict(value or {})
        return cls(
            name=str(row.get("name") or row.get("data_name") or "").strip(),
            required_paths=list(dict.fromkeys(
                str(item).strip()
                for item in row.get("required_paths") or []
                if str(item).strip()
            )),
        )


@dataclass(frozen=True)
class CapabilityContract:
    """A verifiable business obligation carried by one capability task.

    Business data is shared through the run ContextBundle rather than through
    point-to-point bindings.  The contract therefore describes only semantic
    data expectations, user parameters, output names and mutation permission.
    """

    contract_id: str
    description: str
    required_data: list[DataRequirement] = field(default_factory=list)
    required_parameters: list[BusinessParameterRequirement] = field(default_factory=list)
    promised_data: list[DataGuarantee] = field(default_factory=list)
    acceptance_rule_ids: list[str] = field(default_factory=list)
    forbidden_data_names: list[str] = field(default_factory=list)
    criticality: Criticality = "required"
    mutation_allowed: bool = False
    allowed_terminal_states: list[ContractTerminalState] = field(
        default_factory=lambda: ["completed", "business_empty", "business_insufficient"]
    )

    @classmethod
    def from_dict(cls, value: dict[str, Any], *, contract_id: str = "") -> "CapabilityContract":
        row = dict(value or {})
        return cls(
            contract_id=str(row.get("contract_id") or contract_id).strip(),
            description=str(row.get("description") or "").strip(),
            required_data=[
                DataRequirement.from_dict(item)
                for item in row.get("required_data") or []
                if isinstance(item, dict)
            ],
            required_parameters=[
                BusinessParameterRequirement.from_dict(item)
                for item in row.get("required_parameters") or []
                if isinstance(item, dict)
            ],
            promised_data=[
                DataGuarantee.from_dict(item)
                for item in row.get("promised_data") or []
                if isinstance(item, dict)
            ],
            acceptance_rule_ids=list(dict.fromkeys(
                str(item).strip()
                for item in row.get("acceptance_rule_ids") or []
                if str(item).strip()
            )),
            forbidden_data_names=list(dict.fromkeys(
                str(item).strip()
                for item in row.get("forbidden_data_names") or []
                if str(item).strip()
            )),
            criticality=(
                "optional" if str(row.get("criticality") or "required").lower() == "optional"
                else "required"
            ),
            mutation_allowed=bool(row.get("mutation_allowed", False)),
            allowed_terminal_states=list(dict.fromkeys(
                str(item).strip()
                for item in row.get("allowed_terminal_states")
                or ["completed", "business_empty", "business_insufficient"]
                if str(item).strip()
            )),
        )

    def input_data_names(self, *, required_only: bool = False) -> list[str]:
        return list(dict.fromkeys(
            item.name for item in self.required_data
            if item.name and (item.required or not required_only)
        ))

    def parameter_requirements(self, *, required_only: bool = False) -> list[BusinessParameterRequirement]:
        return [
            item for item in self.required_parameters
            if item.parameter_id and (item.required or not required_only)
        ]

    def output_data_names(self) -> list[str]:
        return list(dict.fromkeys(item.name for item in self.promised_data if item.name))

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
    accepted_data_patterns: list[str] = field(default_factory=lambda: ["*"])
    produced_data_patterns: list[str] = field(default_factory=lambda: ["*"])
    accepted_business_parameter_patterns: list[str] = field(default_factory=list)
    input_data_examples: list[str] = field(default_factory=list)
    output_data_examples: list[str] = field(default_factory=list)
    allowed_acceptance_rule_ids: list[str] = field(default_factory=list)
    required_runtime_context_names: list[str] = field(default_factory=list)
    allowed_information_sources: list[str] = field(default_factory=list)
    mutation_allowed: bool = False
    completion_principles: list[str] = field(default_factory=list)

    def safe_for_main_agent(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CapabilityTask:
    """One MainAgent-selected Worker task with semantic data contracts."""

    task_id: str
    worker_id: str
    boundary_id: str
    objective: str
    contracts: list[CapabilityContract]
    business_parameters: dict[str, Any] = field(default_factory=dict)
    priority: int = 1

    @classmethod
    def from_dict(cls, value: dict[str, Any], *, task_id: str = "") -> "CapabilityTask":
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
            priority=max(0, min(10, int(row.get("priority") or 1))),
        )

    def input_data_names(self, *, required_only: bool = False) -> list[str]:
        return list(dict.fromkeys(
            name
            for contract in self.contracts
            for name in contract.input_data_names(required_only=required_only)
        ))

    def output_data_names(self) -> list[str]:
        return list(dict.fromkeys(
            name for contract in self.contracts for name in contract.output_data_names()
        ))

    def acceptance_rule_ids(self) -> list[str]:
        return list(dict.fromkeys(
            rule for contract in self.contracts for rule in contract.acceptance_rule_ids
        ))

    def mutation_allowed(self) -> bool:
        return any(contract.mutation_allowed for contract in self.contracts)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResolvedCapabilityTask:
    task: CapabilityTask
    assigned_worker_id: str
    assigned_agent_id: str
    allowed_tool_ids: list[str]
    execution_mode: str
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
