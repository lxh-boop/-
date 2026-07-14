from __future__ import annotations

import sqlite3

import pandas as pd

from news_db_sync import sync_event_cache_to_agent_db


def test_news_sync_preserves_content_and_creates_multiple_chunks(tmp_path) -> None:
    db_path = tmp_path / "agent_quant.db"
    content = " ".join(f"Revenue update {index} improved!" for index in range(120))
    events = pd.DataFrame(
        [
            {
                "date": "2026-06-23",
                "code": "000001",
                "name": "Ping An Bank",
                "title": "Ping An Bank revenue update",
                "summary": "Revenue and margin improved.",
                "content": content,
                "source": "unit_test_news",
                "url": "https://example.test/news/1",
                "publish_time": "2026-06-23 10:00:00",
            }
        ]
    )

    result = sync_event_cache_to_agent_db(
        stock_pool={"000001": "Ping An Bank"},
        db_path=db_path,
        events=events,
    )

    assert result.event_rows == 1
    assert result.chunk_rows > 1

    with sqlite3.connect(db_path) as conn:
        event_row = conn.execute("SELECT title, summary, content, content_level FROM news_event").fetchone()
        chunk_rows = conn.execute(
            "SELECT chunk_index, chunk_text, content_level FROM news_chunk ORDER BY chunk_index"
        ).fetchall()

    assert event_row == (
        "Ping An Bank revenue update",
        "Revenue and margin improved.",
        content,
        "full_text",
    )
    assert len(chunk_rows) == result.chunk_rows
    assert any("Revenue update 119 improved" in row[1] for row in chunk_rows)
    assert {row[2] for row in chunk_rows} == {"full_text"}
    assert result.chunk_statistics["event_count"] == 1
    assert result.chunk_statistics["content_level_distribution"] == {"full_text": 1}
    assert result.chunk_statistics["duplicate_chunk_count"] == 0
    assert result.chunk_statistics["text_length_p50"] > 0
    assert result.chunk_statistics["event_to_chunk_distribution"]["multi_chunk_events"] == 1


def test_news_sync_marks_title_only_without_faking_body_and_replaces_old_chunks(tmp_path) -> None:
    db_path = tmp_path / "agent_quant.db"
    events = pd.DataFrame(
        [
            {
                "date": "2026-06-23",
                "code": "000001",
                "name": "Ping An Bank",
                "title": "Ping An Bank title only",
                "summary": "",
                "content": "",
                "source": "unit_test_news",
                "url": "https://example.test/news/title-only",
                "publish_time": "2026-06-23 10:00:00",
            }
        ]
    )

    first = sync_event_cache_to_agent_db(stock_pool={"000001": "Ping An Bank"}, db_path=db_path, events=events)
    second = sync_event_cache_to_agent_db(stock_pool={"000001": "Ping An Bank"}, db_path=db_path, events=events)

    assert first.chunk_rows == 1
    assert second.chunk_rows == 1
    with sqlite3.connect(db_path) as conn:
        event_row = conn.execute("SELECT title, summary, content, content_level FROM news_event").fetchone()
        chunk_rows = conn.execute("SELECT chunk_text, content_level FROM news_chunk").fetchall()

    assert event_row == ("Ping An Bank title only", "", "", "title_only")
    assert len(chunk_rows) == 1
    assert chunk_rows[0][0] == "Ping An Bank title only"
    assert chunk_rows[0][1] == "title_only"
    assert second.chunk_statistics["empty_content_count"] == 1
    assert second.chunk_statistics["duplicate_chunk_count"] == 0


def test_news_sync_does_not_downgrade_existing_full_text(tmp_path) -> None:
    db_path = tmp_path / "agent_quant.db"
    full_content = " ".join(f"Full article sentence {index} improved!" for index in range(120))
    first_events = pd.DataFrame(
        [
            {
                "date": "2026-06-23",
                "code": "000001",
                "name": "Ping An Bank",
                "title": "Ping An Bank full article",
                "summary": "Summary text",
                "content": full_content,
                "source": "unit_test_news",
                "url": "https://example.test/news/1",
                "publish_time": "2026-06-23 10:00:00",
            }
        ]
    )
    degraded_events = first_events.copy()
    degraded_events["content"] = ""
    degraded_events["summary"] = ""

    sync_event_cache_to_agent_db(stock_pool={"000001": "Ping An Bank"}, db_path=db_path, events=first_events)
    sync_event_cache_to_agent_db(stock_pool={"000001": "Ping An Bank"}, db_path=db_path, events=degraded_events)

    with sqlite3.connect(db_path) as conn:
        event_row = conn.execute("SELECT content, content_level FROM news_event").fetchone()
        chunk_rows = conn.execute("SELECT chunk_text, content_level FROM news_chunk ORDER BY chunk_index").fetchall()

    assert event_row == (full_content, "full_text")
    assert len(chunk_rows) > 1
    assert {row[1] for row in chunk_rows} == {"full_text"}
    assert any("Full article sentence 79" in row[0] for row in chunk_rows)
