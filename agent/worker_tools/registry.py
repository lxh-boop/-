"""Run-scoped registry and capability-scoped view for Worker-private tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from agent.tool_runtime import (
    TOOL_VISIBILITY_WORKER_PRIVATE,
    ToolDefinition,
    ToolRegistry,
)

from .evidence import build_evidence_tool_definitions
from .diagnostic import build_diagnostic_tool_definitions
from .impact import build_impact_tool_definitions
from .portfolio import build_portfolio_tool_definitions
from .proposal import build_proposal_tool_definitions
from .risk import build_risk_tool_definitions
from .backends import (
    DiagnosticToolBackend,
    EvidenceToolBackend,
    ImpactToolBackend,
    PortfolioToolBackend,
    RiskToolBackend,
)


@dataclass(frozen=True)
class WorkerToolDirectory:
    """Private capability-to-tool projection generated from registry metadata."""

    registry: ToolRegistry
    required_outputs_by_capability: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    max_steps_by_capability: dict[str, int] = field(default_factory=dict)

    def allowed_tool_names(self, capability_id: str) -> list[str]:
        return [
            definition.name
            for definition in self.registry.list(
                visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
            )
            if str(capability_id or "")
            in set(definition.allowed_capability_ids)
        ]

    def allows(self, capability_id: str, tool_name: str) -> bool:
        definition = self.registry.get(tool_name)
        return bool(
            definition
            and definition.visibility == TOOL_VISIBILITY_WORKER_PRIVATE
            and str(capability_id or "")
            in set(definition.allowed_capability_ids)
        )

    def get_allowed(
        self,
        capability_id: str,
        tool_name: str,
    ) -> ToolDefinition | None:
        definition = self.registry.get(tool_name)
        return definition if self.allows(capability_id, tool_name) else None

    def required_outputs(self, capability_id: str) -> list[str]:
        return list(
            self.required_outputs_by_capability.get(
                str(capability_id or ""),
                (),
            )
        )

    def max_steps(self, capability_id: str) -> int:
        return max(
            1,
            int(
                self.max_steps_by_capability.get(
                    str(capability_id or ""),
                    8,
                )
            ),
        )

    def safe_catalog(self, capability_id: str) -> list[dict]:
        rows: list[dict] = []
        for definition in self.registry.list(
            visibility=TOOL_VISIBILITY_WORKER_PRIVATE
        ):
            if str(capability_id or "") not in set(
                definition.allowed_capability_ids
            ):
                continue
            rows.append(
                {
                    "tool_name": definition.name,
                    "description": definition.description,
                    "required_inputs": list(
                        definition.input_schema.get("required") or []
                    ),
                    "required_dependency_outputs": list(
                        definition.required_dependency_outputs
                    ),
                    "produced_outputs": list(
                        definition.produced_outputs
                    ),
                    "operation_type": definition.operation_type,
                    "side_effects": list(definition.side_effects),
                    "idempotency": definition.idempotency,
                }
            )
        return rows


def build_worker_tool_registry(
    *,
    evidence_backend: EvidenceToolBackend,
    portfolio_backend: PortfolioToolBackend,
    risk_backend: RiskToolBackend,
    diagnostic_backend: DiagnosticToolBackend,
    impact_backend: ImpactToolBackend | None = None,
) -> ToolRegistry:
    """Build private tool definitions against run-scoped dependencies."""

    definitions = [
        *build_evidence_tool_definitions(evidence_backend),
        *build_portfolio_tool_definitions(portfolio_backend),
        *build_risk_tool_definitions(risk_backend),
        *build_diagnostic_tool_definitions(diagnostic_backend),
        *build_proposal_tool_definitions(),
    ]
    if impact_backend is not None:
        definitions.extend(build_impact_tool_definitions(impact_backend))
    return ToolRegistry(definitions)


def build_worker_tool_directory(
    registry: ToolRegistry,
    *,
    required_outputs_by_capability: dict[
        str, Iterable[str]
    ] | None = None,
    max_steps_by_capability: dict[str, int] | None = None,
) -> WorkerToolDirectory:
    policy = required_outputs_by_capability or {
        "evidence.retrieve": ("evidence_results", "ingestion_results"),
        "evidence.analyze_entity": ("entity_evidence_results",),
        "evidence.ingest": ("ingestion_results",),
        "portfolio.load_snapshot": ("portfolio_snapshot",),
        "portfolio.analyze": ("portfolio_snapshot",),
        "risk.analyze": ("risk_analysis",),
        "graph.map_evidence_to_holdings": (
            "impact_paths",
            "impact_summary",
        ),
        "strategy.build_proposal": ("proposal",),
        "system.check_graph_connectivity": (
            "diagnostic_analysis",
        ),
    }
    return WorkerToolDirectory(
        registry=registry,
        required_outputs_by_capability={
            str(capability_id): tuple(
                str(output)
                for output in outputs
                if str(output).strip()
            )
            for capability_id, outputs in policy.items()
        },
        max_steps_by_capability={
            "strategy.build_proposal": 1,
            **dict(max_steps_by_capability or {}),
        },
    )
