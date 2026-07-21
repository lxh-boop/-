"""Legacy CLI/API wrapper that delegates to the formal single Agent entry."""
from __future__ import annotations

import argparse
from typing import Any

from core.llm import LLMRuntimeSettings
from agent.schemas import AgentResponse


def run_agent(
    query: str,
    model_name: str | None = None,
    topk: int = 10,
    prompt_text: str | None = None,
    llm_api_key: str | None = None,
    llm_base_url: str = "",
    llm_model: str = "",
    llm_cache_row: dict | None = None,
    llm_settings: LLMRuntimeSettings | None = None,
    **kwargs: Any,
) -> AgentResponse:
    del model_name, prompt_text, llm_cache_row
    from agent.executor import run_agent_request

    result = run_agent_request(
        query,
        top_k=topk,
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url or None,
        llm_model=llm_model or None,
        llm_settings=llm_settings,
        **kwargs,
    )
    return AgentResponse(
        answer=str(result.get("answer") or ""),
        intent="agent_collaboration_v2",
        tool_calls=[],
        data=dict(result or {}),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="金融分析 Agent 单一入口")
    parser.add_argument("--query", type=str, default="")
    parser.add_argument("--topk", type=int, default=10)
    args = parser.parse_args()
    if args.query:
        print(run_agent(args.query, topk=args.topk).answer)
        return
    print("金融分析 Agent 已启动，输入 exit 退出。")
    while True:
        query = input("用户：").strip()
        if query.lower() in {"exit", "quit", "q"}:
            break
        if query:
            print(run_agent(query, topk=args.topk).answer)


if __name__ == "__main__":
    main()
