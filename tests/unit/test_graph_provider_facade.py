"""Regression tests for atomic GraphProviderAdapter operations."""

from __future__ import annotations

from dataclasses import fields
from types import SimpleNamespace
from unittest.mock import Mock

from agent.graph.contracts import GraphNodeKind, GraphRef
from agent.graph.provider_adapter import GraphProviderAdapter
from agent.graph.providers.common import (
    ProviderIdentityResolver,
    records_from_payload,
    sources_from_payload,
)


def _object_ref() -> GraphRef:
    return GraphRef(
        graph_id="financial_graph",
        node_id="object:600519",
        node_kind=GraphNodeKind.OBJECT,
        role="focus",
    )


def test_payload_helpers_preserve_existing_service_shapes() -> None:
    payload = {
        "data": {
            "events": [{"id": "event-1"}],
            "sources": [{"source_id": "source-1"}],
        }
    }

    assert records_from_payload(payload) == [{"id": "event-1"}]
    assert sources_from_payload(payload) == [{"source_id": "source-1"}]


def test_identity_resolver_keeps_provider_identifier_private() -> None:
    identity = SimpleNamespace(
        get_identity_value=Mock(return_value="600519.SH"),
    )

    value = ProviderIdentityResolver(identity).provider_symbol(_object_ref())

    assert value == "600519"
    identity.get_identity_value.assert_called_once()


def test_graph_provider_adapter_delegates_to_domain_adapters() -> None:
    adapter = GraphProviderAdapter(
        identity=SimpleNamespace(),
        evidence_ingestion=SimpleNamespace(),
        portfolio_graph=SimpleNamespace(),
    )
    adapter._evidence_provider = Mock()
    adapter._portfolio_provider = Mock()
    adapter._risk_provider = Mock()
    adapter._evidence_provider.analyze_entities.return_value = {"success": True}
    adapter._evidence_provider.search_evidence.return_value = {"success": True}
    adapter._evidence_provider.ingest_evidence.return_value = {"success": True}
    adapter._portfolio_provider.read_portfolio_state.return_value = {"success": True}
    adapter._portfolio_provider.materialize_portfolio_snapshot.return_value = {"success": True}
    adapter._risk_provider.analyze_risk.return_value = {"success": True}
    ref = _object_ref()

    assert adapter.analyze_entities(
        [ref],
        user_id="u1",
        output_dir="outputs",
        db_path=None,
    ) == {"success": True}
    assert adapter.search_evidence(
        [ref],
        query="分析",
        top_k=5,
        output_dir="outputs",
        db_path=None,
    ) == {"success": True}
    assert adapter.ingest_evidence(
        [{"focus_ref": ref.to_dict(), "records": []}],
        source_task_id="task-1",
        source_agent_id="worker",
    ) == {"success": True}
    assert adapter.read_portfolio_state(
        user_id="u1",
        output_dir="outputs",
        db_path=None,
    ) == {"success": True}
    assert adapter.materialize_portfolio_snapshot(
        {"success": True},
        user_id="u1",
        as_of_time="",
        source_task_id="task-2",
        source_agent_id="worker",
    ) == {"success": True}
    assert adapter.analyze_risk(
        user_id="u1",
        output_dir="outputs",
        db_path=None,
    ) == {"success": True}

    adapter._evidence_provider.analyze_entities.assert_called_once()
    adapter._evidence_provider.search_evidence.assert_called_once()
    adapter._evidence_provider.ingest_evidence.assert_called_once()
    adapter._portfolio_provider.read_portfolio_state.assert_called_once()
    adapter._portfolio_provider.materialize_portfolio_snapshot.assert_called_once()
    adapter._risk_provider.analyze_risk.assert_called_once()


def test_graph_provider_adapter_keeps_original_dataclass_fields() -> None:
    assert [item.name for item in fields(GraphProviderAdapter)] == [
        "identity",
        "evidence_ingestion",
        "portfolio_graph",
    ]
