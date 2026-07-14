from __future__ import annotations

from rag.chunkers import chunk_announcement, chunk_decision_log, chunk_industry_rule, chunk_news


def test_chunk_news_keeps_metadata_and_text() -> None:
    chunks = chunk_news(
        {
            "news_id": "news_001",
            "title": "宁德时代发布公告",
            "summary": "公司提示经营风险",
            "content": "公司表示销量不及预期，需关注需求下降风险。",
            "source": "交易所",
            "publish_time": "2026-06-11 10:00:00",
            "trade_date": "2026-06-11",
            "stock_codes": ["300750"],
            "industry": "动力电池",
            "event_type": "风险提示",
            "url": "https://example.com/news",
        }
    )

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.news_id == "news_001"
    assert chunk.stock_codes == ["300750"]
    assert "销量不及预期" in chunk.chunk_text
    assert chunk.source == "交易所"


def test_chunk_announcement_splits_by_sections() -> None:
    chunks = chunk_announcement(
        {
            "news_id": "ann_001",
            "title": "重大合同公告",
            "content": "一、合同主要内容。公司签署重大合同。\n二、对公司的影响。预计改善收入。\n风险提示。合同履行存在不确定性。",
            "publish_time": "2026-06-11 10:00:00",
            "trade_date": "2026-06-11",
            "stock_code": "000001",
            "event_type": "重大合同",
        }
    )

    section_titles = [chunk.section_title for chunk in chunks]
    assert any("一、合同主要内容" in title for title in section_titles)
    assert any("二、对公司的影响" in title for title in section_titles)
    assert any("风险提示" in title for title in section_titles)
    assert all("重大合同公告" in chunk.chunk_text for chunk in chunks)


def test_decision_and_rule_chunk_one_record_one_chunk() -> None:
    decision = chunk_decision_log(
        {
            "decision_id": "decision_001",
            "trade_date": "2026-06-11",
            "stock_code": "300750",
            "final_action": "down_weight",
            "final_reason": "重大负面新闻触发降权。",
        }
    )
    rule = chunk_industry_rule(
        {
            "rule_id": "rule_001",
            "event_keyword": "锂价下跌",
            "affected_industry": "动力电池",
            "impact_direction": "positive",
            "description": "成本压力缓解。",
        }
    )

    assert decision.section_title == "agent_decision_log"
    assert "down_weight" in decision.chunk_text
    assert rule.section_title == "industry_event_rule"
    assert "锂价下跌" in rule.chunk_text
