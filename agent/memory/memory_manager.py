from __future__ import annotations

from pathlib import Path
from typing import Any

from .memory_candidate_extractor import MemoryCandidateExtractor
from .memory_consolidator import MemoryConsolidator
from .memory_context_selector import MemoryContextSelector
from .memory_policy import MemoryPolicy
from .memory_pruner import MemoryPruner
from .memory_retrieval_types import MemoryRetrievalRequest
from .memory_retriever import MemoryRetriever
from .memory_sanitizer import MemorySanitizer
from .memory_store import SQLiteMemoryStore
from .memory_types import MemoryRecord, MemoryScope, MemoryStatus, MemoryType
from .working_memory import WorkingMemory


class MemoryManager:
    def __init__(
        self,
        *,
        db_path: str | Path | None = None,
        working_memory: WorkingMemory | None = None,
        store: SQLiteMemoryStore | None = None,
        retriever: MemoryRetriever | None = None,
        selector: MemoryContextSelector | None = None,
        extractor: MemoryCandidateExtractor | None = None,
        consolidator: MemoryConsolidator | None = None,
        pruner: MemoryPruner | None = None,
        policy: MemoryPolicy | None = None,
        sanitizer: MemorySanitizer | None = None,
    ) -> None:
        self.policy = policy or MemoryPolicy.default()
        self.sanitizer = sanitizer or MemorySanitizer(self.policy)
        self.working_memory = working_memory or WorkingMemory(
            policy=self.policy,
            sanitizer=self.sanitizer,
        )
        self.store = store or SQLiteMemoryStore(
            db_path,
            policy=self.policy,
            sanitizer=self.sanitizer,
        )
        self.retriever = retriever or MemoryRetriever(
            working_memory=self.working_memory,
            store=self.store,
        )
        self.selector = selector or MemoryContextSelector()
        self.extractor = extractor or MemoryCandidateExtractor(
            sanitizer=self.sanitizer
        )
        self.consolidator = consolidator or MemoryConsolidator()
        self.pruner = pruner or MemoryPruner()

    def remember(
        self,
        record: MemoryRecord | dict[str, Any] | str | None = None,
        *,
        user_id: str = "default_user",
        content: str = "",
        memory_type: MemoryType | str = MemoryType.WORKING,
        memory_subtype: str = "",
        source_type: str = "",
        source_id: str = "",
        conversation_id: str = "",
        run_id: str = "",
        task_id: str = "",
        scope: MemoryScope | str = MemoryScope.CONVERSATION,
        topics: list[str] | None = None,
        stock_codes: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        user_confirmed: bool = False,
        long_term: bool | None = None,
        ttl_seconds: int | None = None,
    ) -> MemoryRecord:
        memory = _coerce_record(
            record,
            user_id=user_id,
            content=content,
            memory_type=memory_type,
            memory_subtype=memory_subtype,
            source_type=source_type,
            source_id=source_id,
            conversation_id=conversation_id,
            run_id=run_id,
            task_id=task_id,
            scope=scope,
            topics=topics,
            stock_codes=stock_codes,
            metadata=metadata,
        )
        if user_confirmed:
            memory.metadata["user_confirmed"] = True
            if not memory.source_type:
                memory.source_type = "confirmed_user_preference"
        safe = self.sanitizer.sanitize_record(memory)
        if long_term is None:
            long_term = safe.memory_type != MemoryType.WORKING
        if not long_term or safe.memory_type == MemoryType.WORKING:
            return self.working_memory.put(safe, ttl_seconds=ttl_seconds)
        safe.status = MemoryStatus.ACTIVE
        self.policy.assert_can_store(safe)
        return self.store.upsert(safe)

    def remember_candidate(
        self,
        value: Any,
        *,
        user_id: str = "default_user",
        source_type: str = "",
        ttl_seconds: int = 1800,
    ) -> list[MemoryRecord]:
        candidates = self.extractor.extract(
            value,
            source_type=source_type,
            user_id=user_id,
        )
        stored: list[MemoryRecord] = []
        for candidate in candidates:
            original_type = candidate.memory_type.value
            candidate.status = MemoryStatus.CANDIDATE
            candidate.memory_type = MemoryType.WORKING
            candidate.metadata = {
                **dict(candidate.metadata or {}),
                "candidate_original_type": candidate.memory_subtype or original_type,
            }
            stored.append(
                self.working_memory.put(candidate, ttl_seconds=ttl_seconds)
            )
        return stored

    def retrieve(self, **kwargs: Any):
        return self.retriever.retrieve(**kwargs)

    def retrieve_for_context(
        self,
        *,
        request: MemoryRetrievalRequest | None = None,
        user_id: str = "",
        query: str = "",
        candidate_top_n: int = 40,
        relevance_threshold: float = 0.42,
        token_budget: int = 360,
        task_type: str = "",
        agent_role: str = "supervisor",
        entities: dict[str, Any] | None = None,
        topics: list[str] | None = None,
        stock_codes: list[str] | None = None,
        memory_types: list[MemoryType | str] | None = None,
        created_after: str = "",
        created_before: str = "",
        min_importance: float = 0.0,
        include_working: bool = False,
        include_long_term: bool = True,
        conversation_id: str = "",
        run_id: str = "",
        limit: int | None = None,
    ) -> dict[str, Any]:
        # One request -> one storage retrieval.  The larger TopN candidate pool
        # is filtered in memory by MemoryContextSelector; no second DB query.
        req = request or MemoryRetrievalRequest(
            user_id=user_id,
            query=query,
            conversation_id=conversation_id,
            run_id=run_id,
            task_type=task_type,
            agent_role=agent_role,
            entities=dict(entities or {}),
            topics=list(topics or []),
            stock_codes=list(stock_codes or []),
            memory_types=list(memory_types or []),
            created_after=created_after,
            created_before=created_before,
            candidate_top_n=int(limit or candidate_top_n),
            relevance_threshold=relevance_threshold,
            token_budget=token_budget,
            min_importance=min_importance,
            include_working=include_working,
            include_long_term=include_long_term,
        )
        req = req.normalized()
        candidates = self.retriever.retrieve(
            user_id=req.user_id,
            query=req.query,
            memory_types=req.memory_types or None,
            topics=req.topics or None,
            stock_codes=req.stock_codes or None,
            created_after=req.created_after,
            created_before=req.created_before,
            min_importance=req.min_importance,
            include_working=req.include_working,
            include_long_term=req.include_long_term,
            candidate_top_n=req.candidate_top_n,
        )
        selection = self.selector.select(candidates, req)

        safe_items: list[dict[str, Any]] = []
        for item in selection.selected:
            safe = dict(item)
            safe["memory"] = self.sanitizer.sanitize_for_llm(
                safe.get("memory") or {}
            )
            safe_items.append(safe)

        diagnostics = (
            selection.diagnostics.to_dict()
            if selection.diagnostics is not None
            else {}
        )
        return {
            "user_id": req.user_id,
            "query": req.query,
            "retrieval_id": req.retrieval_id,
            "items": safe_items,
            "diagnostics": diagnostics,
            "policy": {
                "secrets_removed": True,
                "long_term_user_facts_require_confirmation": True,
                "memory_manager_has_no_commit_permission": True,
                "context_admission": "relevance_threshold_then_entity_task_time_token_budget",
                "fixed_top_k_context_admission": False,
                "candidate_pool_top_n": req.candidate_top_n,
                "relevance_threshold": req.relevance_threshold,
                "token_budget": req.token_budget,
            },
        }

    def forget(self, memory_id: str, *, user_id: str, hard: bool = False) -> bool:
        working_deleted = self.working_memory.delete(memory_id, user_id=user_id)
        store_deleted = self.store.delete(memory_id, user_id=user_id, hard=hard)
        return working_deleted or store_deleted

    def consolidate(self, *, user_id: str, limit: int = 500) -> dict[str, Any]:
        return self.consolidator.consolidate_store(
            self.store,
            user_id=user_id,
            limit=limit,
        )

    def prune(
        self,
        *,
        user_id: str,
        hard: bool = False,
        limit: int = 2000,
    ) -> dict[str, Any]:
        return self.pruner.prune_store(
            self.store,
            user_id=user_id,
            hard=hard,
            limit=limit,
        )


def _coerce_record(
    record: MemoryRecord | dict[str, Any] | str | None,
    **defaults: Any,
) -> MemoryRecord:
    if isinstance(record, MemoryRecord):
        return MemoryRecord.from_dict({**defaults, **record.to_dict()})
    if isinstance(record, dict):
        return MemoryRecord.from_dict({**defaults, **record})
    if isinstance(record, str):
        defaults["content"] = record
    return MemoryRecord(**defaults)


__all__ = ["MemoryManager"]
