"""Domain-neutral DAG contracts and validation.

Main-Agent capability plans use this module today. Worker-Agent tool plans can
reuse the same node, dependency, cycle, ordering, and terminal-coverage rules
without depending on Main-Agent or legacy intent contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


class DagValidationError(ValueError):
    """Raised when a DAG contract is structurally invalid."""

    def __init__(self, code: str, *, node_ids: Iterable[str] = ()) -> None:
        self.code = str(code or "dag_invalid")
        self.node_ids = tuple(
            str(node_id).strip()
            for node_id in node_ids
            if str(node_id).strip()
        )
        detail = ",".join(self.node_ids)
        super().__init__(f"{self.code}:{detail}" if detail else self.code)


@dataclass(frozen=True)
class DagNode:
    """Minimal node contract shared by Main and Worker planning layers."""

    node_id: str
    dependency_ids: tuple[str, ...] = ()
    terminal: bool = False

    @classmethod
    def from_values(
        cls,
        node_id: str,
        dependency_ids: Iterable[str] = (),
        *,
        terminal: bool = False,
    ) -> "DagNode":
        return cls(
            node_id=str(node_id or "").strip(),
            dependency_ids=tuple(
                dict.fromkeys(
                    str(dependency_id).strip()
                    for dependency_id in dependency_ids
                    if str(dependency_id).strip()
                )
            ),
            terminal=bool(terminal),
        )


@dataclass(frozen=True)
class DagValidationResult:
    ordered_node_ids: tuple[str, ...]
    terminal_node_ids: tuple[str, ...]
    covered_node_ids: tuple[str, ...]


class DagValidator:
    """Validate identifiers, references, cycles, order, and terminal coverage."""

    def __init__(self, *, max_nodes: int | None = None) -> None:
        self.max_nodes = max_nodes

    def validate(
        self,
        nodes: Iterable[DagNode],
        *,
        require_terminal_coverage: bool = False,
    ) -> DagValidationResult:
        rows = list(nodes)
        if self.max_nodes is not None and len(rows) > self.max_nodes:
            raise DagValidationError("dag_too_many_nodes")

        by_id: dict[str, DagNode] = {}
        input_order: list[str] = []
        for node in rows:
            node_id = str(node.node_id or "").strip()
            if not node_id:
                raise DagValidationError("dag_empty_node_id")
            if node_id in by_id:
                raise DagValidationError(
                    "dag_duplicate_node_id",
                    node_ids=(node_id,),
                )
            by_id[node_id] = node
            input_order.append(node_id)

        for node_id in input_order:
            for dependency_id in by_id[node_id].dependency_ids:
                if dependency_id == node_id:
                    raise DagValidationError(
                        "dag_self_dependency",
                        node_ids=(node_id,),
                    )
                if dependency_id not in by_id:
                    raise DagValidationError(
                        "dag_unknown_dependency",
                        node_ids=(node_id, dependency_id),
                    )

        pending = list(input_order)
        completed: set[str] = set()
        ordered: list[str] = []
        while pending:
            ready = [
                node_id
                for node_id in pending
                if all(
                    dependency_id in completed
                    for dependency_id in by_id[node_id].dependency_ids
                )
            ]
            if not ready:
                raise DagValidationError(
                    "dag_dependency_cycle",
                    node_ids=tuple(pending),
                )
            for node_id in ready:
                ordered.append(node_id)
                completed.add(node_id)
                pending.remove(node_id)

        terminal_ids = tuple(
            node_id for node_id in input_order if by_id[node_id].terminal
        )
        covered = self._validate_terminal_coverage(
            by_id,
            terminal_ids=terminal_ids,
            require_terminal_coverage=require_terminal_coverage,
        )
        return DagValidationResult(
            ordered_node_ids=tuple(ordered),
            terminal_node_ids=terminal_ids,
            covered_node_ids=tuple(
                node_id for node_id in input_order if node_id in covered
            ),
        )

    @staticmethod
    def _validate_terminal_coverage(
        by_id: dict[str, DagNode],
        *,
        terminal_ids: tuple[str, ...],
        require_terminal_coverage: bool,
    ) -> set[str]:
        if not terminal_ids:
            if require_terminal_coverage:
                raise DagValidationError("dag_terminal_missing")
            return set(by_id)

        depended_on = {
            dependency_id
            for node in by_id.values()
            for dependency_id in node.dependency_ids
        }
        non_terminal = set(terminal_ids).intersection(depended_on)
        if non_terminal:
            raise DagValidationError(
                "dag_terminal_has_dependents",
                node_ids=sorted(non_terminal),
            )

        covered = set(terminal_ids)
        stack = list(terminal_ids)
        while stack:
            node_id = stack.pop()
            for dependency_id in by_id[node_id].dependency_ids:
                if dependency_id in covered:
                    continue
                covered.add(dependency_id)
                stack.append(dependency_id)

        if require_terminal_coverage:
            uncovered = set(by_id).difference(covered)
            if uncovered:
                raise DagValidationError(
                    "dag_terminal_missing_branches",
                    node_ids=sorted(uncovered),
                )
        return covered


__all__ = [
    "DagNode",
    "DagValidationError",
    "DagValidationResult",
    "DagValidator",
]
