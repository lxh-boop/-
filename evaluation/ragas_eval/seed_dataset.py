from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from config import AGENT_QUANT_DB_PATH


def _normalize_decision_time(trade_date: str, publish_time: str) -> str:
    date_text = str(trade_date or "").strip()
    if not date_text:
        date_text = str(publish_time or "").strip().split(" ")[0]
    if not date_text:
        date_text = datetime.now().strftime("%Y-%m-%d")
    date_text = date_text.replace("/", "-")
    if len(date_text) == 8 and date_text.isdigit():
        date_text = f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:]}"
    return f"{date_text}T15:00:00+08:00"


def _compact_text(value: Any, max_len: int = 260) -> str:
    text = " ".join(str(value or "").split())
    return text[:max_len]


def build_seed_cases(
    *,
    db_path: str | Path = AGENT_QUANT_DB_PATH,
    limit: int = 5,
) -> list[dict[str, Any]]:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT
            chunk_id,
            news_id,
            stock_code,
            event_type,
            source,
            publish_time,
            trade_date,
            section_title,
            chunk_text
        FROM news_chunk
        WHERE length(trim(chunk_text)) >= 40
          AND stock_code IS NOT NULL
          AND trim(stock_code) <> ''
        ORDER BY
          CASE WHEN event_type IN ('shareholder_reduce', 'penalty', 'litigation', 'loss', 'negative') THEN 0 ELSE 1 END,
          publish_time DESC,
          chunk_id ASC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    cases: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        stock_code = str(row["stock_code"] or "").split(".")[0].zfill(6)
        event_type = str(row["event_type"] or "新闻事件")
        reference = _compact_text(row["chunk_text"], max_len=320)
        query_hint = _compact_text(row["chunk_text"], max_len=80)
        cases.append(
            {
                "case_id": f"auto_seed_{index:03d}_{row['chunk_id']}",
                "user_input": f"请基于本地新闻证据说明 {stock_code} 近期是否存在 {event_type} 相关风险或事件：{query_hint}",
                "stock_code": stock_code,
                "decision_time": _normalize_decision_time(row["trade_date"], row["publish_time"]),
                "reference": reference,
                "reference_context_ids": [str(row["chunk_id"])],
                "allowed_related_stock_codes": [],
                "tags": ["auto_seed", "local_news_chunk", str(event_type)],
                "metadata": {
                    "source": "auto_seed_from_local_news_chunk",
                    "gold_level": "diagnostic_not_human_gold",
                    "news_id": row["news_id"],
                    "chunk_id": row["chunk_id"],
                    "event_type": event_type,
                    "publish_time": row["publish_time"],
                    "trade_date": row["trade_date"],
                    "news_source": row["source"],
                    "note": "由本地真实 news_chunk 自动生成，用于 Ragas 接入诊断；不能替代人工评测集。",
                },
            }
        )
    return cases


def write_jsonl(cases: list[dict[str, Any]], output: str | Path) -> Path:
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as file:
        for case in cases:
            file.write(json.dumps(case, ensure_ascii=False) + "\n")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a small diagnostic Ragas dataset from local news_chunk rows.")
    parser.add_argument("--db-path", default=str(AGENT_QUANT_DB_PATH))
    parser.add_argument("--output", default=str(Path("data") / "evaluation" / "rag_eval_auto_seed.jsonl"))
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args(argv)
    cases = build_seed_cases(db_path=args.db_path, limit=args.limit)
    output = write_jsonl(cases, args.output)
    print(f"wrote {len(cases)} diagnostic seed cases: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
