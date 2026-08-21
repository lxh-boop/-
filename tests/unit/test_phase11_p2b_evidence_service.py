from __future__ import annotations

from pathlib import Path

from agent.tool_engine import AGENT_READ, OP_READ, execute_tool, get_tool_registry_v2
from agent.tools import evidence_adapters
from agent.tools.stock_news_tool import query_stock_news
from agent.tools.stock_rag_tool import query_stock_rag
from database.repositories import NewsRepository


def _write_news_fixture(db_path: Path) -> None:
    repo = NewsRepository(db_path)
    repo.insert_news_event(
        {
            "news_id": "news_1",
            "title": "Ping An Bank profit growth",
            "summary": "Profit improved.",
            "content": "Ping An Bank reported profit growth and lower credit risk.",
            "source": "unit_test_news",
            "url": "https://example.test/news/1",
            "publish_time": "2026-06-23 10:00:00",
            "trade_date": "2026-06-23",
        }
    )
    repo.insert_news_stock_mapping(
        {
            "mapping_id": "mapping_1",
            "news_id": "news_1",
            "stock_code": "000001",
            "stock_name": "Ping An Bank",
            "impact_direction": "positive",
            "mapping_confidence": 0.9,
            "evidence_text": "profit growth",
        }
    )


def test_p2b_evidence_tools_registered_with_legacy_aliases() -> None:
    registry = get_tool_registry_v2()
    expected = {
        "evidence.search_news": ["stock_news", "news_search"],
        "evidence.search_rag": ["stock_rag", "rag_search"],
        "evidence.get_stock_evidence": [],
        "evidence.get_market_evidence": [],
    }

    for canonical, aliases in expected.items():
        definition = registry.get(canonical)
        assert definition is not None
        assert definition.name == canonical
        assert definition.operation_type == OP_READ
        for alias in aliases:
            assert registry.get(alias).name == canonical

    assert callable(evidence_adapters.EvidenceSearchNewsAdapter)
    assert callable(evidence_adapters.EvidenceSearchRagAdapter)
    assert callable(evidence_adapters.EvidenceGetStockEvidenceAdapter)
    assert callable(evidence_adapters.EvidenceGetMarketEvidenceAdapter)
    assert registry.get("evidence.mcp_readonly_evidence") is None
    assert registry.get("mcp.readonly.invoke") is None
    assert not hasattr(evidence_adapters, "EvidenceMcpReadonlyAdapter")


def test_p2b_stock_news_legacy_wrapper_and_v2_artifact(tmp_path: Path) -> None:
    db_path = tmp_path / "agent_quant.db"
    _write_news_fixture(db_path)

    legacy = query_stock_news("000001", as_of_date="2026-06-23", db_path=db_path)
    migrated = execute_tool(
        "stock_news",
        {"stock_code": "000001", "as_of_date": "2026-06-23", "limit": 5},
        context={"user_id": "u1", "output_dir": tmp_path, "db_path": db_path},
        agent_type=AGENT_READ,
    )

    assert legacy["status"] == "success"
    assert legacy["events"][0]["news_id"] == "news_1"
    assert migrated.success is True
    assert migrated.metadata["canonical_tool_name"] == "evidence.search_news"
    assert migrated.artifact_id
    assert migrated.data["records"][0]["news_id"] == "news_1"
    assert migrated.data["sources"][0]["source_type"] == "news_event"
    assert migrated.data["evidence_count"] == 1


def test_p2b_stock_rag_legacy_wrapper_and_empty_safe_return(monkeypatch, tmp_path: Path) -> None:
    def fake_retrieve_stock_context(self, *, stock_code: str, query: str, top_k: int = 5, output_dir="outputs"):
        return [
            {
                "date": "2026-06-23",
                "title": "Risk context",
                "source": "unit_test_rag",
                "url": "https://example.test/rag/1",
                "score": 0.88,
                "content": "risk context for stock",
                "chunk_id": "chunk_1",
            }
        ]

    monkeypatch.setattr(
        "agent.services.evidence_service.RagRepository.retrieve_stock_context",
        fake_retrieve_stock_context,
    )

    legacy = query_stock_rag("000001", query="risk", top_k=1, output_dir=tmp_path)
    migrated = execute_tool(
        "rag_search",
        {"stock_code": "000001", "query": "risk", "top_k": 1},
        context={"user_id": "u1", "output_dir": tmp_path, "db_path": tmp_path / "agent_quant.db"},
        agent_type=AGENT_READ,
    )
    invalid = execute_tool(
        "stock_rag",
        {"stock_code": "", "query": "risk"},
        context={"user_id": "u1", "output_dir": tmp_path},
        agent_type=AGENT_READ,
    )

    assert legacy["status"] == "success"
    assert legacy["chunks"][0]["chunk_id"] == "chunk_1"
    assert migrated.success is True
    assert migrated.metadata["canonical_tool_name"] == "evidence.search_rag"
    assert migrated.data["sources"][0]["source_type"] == "rag_chunk"
    assert migrated.data["evidence_count"] == 1
    assert invalid.success is False
    assert invalid.data["records"] == []


def test_p2b_stock_evidence_merges_news_and_rag_sources(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "agent_quant.db"
    _write_news_fixture(db_path)

    def fake_retrieve_stock_context(self, *, stock_code: str, query: str, top_k: int = 5, output_dir="outputs"):
        return [
            {
                "date": "2026-06-23",
                "title": "RAG context",
                "source": "unit_test_rag",
                "url": "https://example.test/rag/1",
                "score": 0.5,
                "content": "RAG evidence",
                "chunk_id": "chunk_1",
            }
        ]

    monkeypatch.setattr(
        "agent.services.evidence_service.RagRepository.retrieve_stock_context",
        fake_retrieve_stock_context,
    )

    result = execute_tool(
        "evidence.get_stock_evidence",
        {"stock_code": "000001", "query": "profit risk", "top_k": 5},
        context={"user_id": "u1", "output_dir": tmp_path, "db_path": db_path},
        agent_type=AGENT_READ,
    )

    source_types = {source["source_type"] for source in result.data["sources"]}
    assert result.success is True
    assert result.data["evidence_count"] == 2
    assert {"news_event", "rag_chunk"} <= source_types
    assert result.data["not_executed"] is True


def test_p2b_rag_unavailable_degrades_safely(monkeypatch, tmp_path: Path) -> None:
    def broken_retrieve(*args, **kwargs):
        raise RuntimeError("index missing")

    monkeypatch.setattr(
        "agent.services.evidence_service.RagRepository.retrieve_stock_context",
        broken_retrieve,
    )

    result = execute_tool(
        "stock_rag",
        {"stock_code": "000001", "query": "risk", "top_k": 3},
        context={"user_id": "u1", "output_dir": tmp_path},
        agent_type=AGENT_READ,
    )

    assert result.success is False
    assert result.data["records"] == []
    assert result.data["chunks"] == []
    assert "rag_unavailable" in result.warnings
