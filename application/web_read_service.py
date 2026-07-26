from __future__ import annotations

import hashlib
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any


class WebReadApplicationService:
    """Read-only application facade used by the React migration.

    The facade composes existing application services. It never writes settings,
    starts a backtest, persists a monitor snapshot, or mutates portfolio state.
    """

    @staticmethod
    def _text(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _event_id(row: dict[str, Any]) -> str:
        raw = "|".join(
            str(row.get(key) or "")
            for key in ("code", "date", "publish_time", "source", "title")
        )
        return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:20]

    @staticmethod
    def _safe_number(value: Any) -> float | int | None:
        try:
            number = float(value)
            if math.isnan(number) or math.isinf(number):
                return None
            return int(number) if number.is_integer() else number
        except Exception:
            return None

    def ranking(self) -> Any:
        from application.dashboard_service import dashboard_service

        return dashboard_service.load_ranking()

    def metrics(self) -> Any:
        from application.dashboard_service import dashboard_service

        return dashboard_service.load_metrics()

    def selected_strategy(self) -> dict[str, Any]:
        from application.model_search_service import load_selected_strategy

        value = load_selected_strategy()
        return value if isinstance(value, dict) else {}

    def dashboard_summary(self) -> dict[str, Any]:
        from application.dashboard_service import dashboard_service

        ranking = self.ranking()
        nav, backtest_metrics, _trades, _predictions = dashboard_service.load_backtest_outputs()
        events = dashboard_service.load_news_events_for_app()
        selected = self.selected_strategy()
        local_cfg = self.public_settings()
        snapshot = dashboard_service.get_ranking_file_snapshot()
        return {
            "ranking": {
                "available": ranking is not None and not getattr(ranking, "empty", True),
                "total": int(len(ranking)) if ranking is not None else 0,
                "signal_date": snapshot.get("signal_date") or "",
                "prediction_date": snapshot.get("prediction_date") or "",
                "updated_at": snapshot.get("mtime_text") if snapshot.get("exists") else None,
            },
            "model": {
                "backend": local_cfg.get("model_backend"),
                "version": local_cfg.get("model_version"),
                "selected_strategy": selected,
                "metrics_available": self.metrics() is not None,
            },
            "backtest": {
                "available": nav is not None and not getattr(nav, "empty", True),
                "metrics": backtest_metrics or {},
            },
            "news": {
                "available": not getattr(events, "empty", True),
                "total": int(len(events)) if events is not None else 0,
            },
            "feature_flags": local_cfg.get("feature_flags", {}),
        }

    def ranking_page(self, *, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        frame = self.ranking()
        if frame is None or getattr(frame, "empty", True):
            return {"records": [], "total": 0, "offset": int(offset), "limit": int(limit)}
        data = frame.copy()
        if "rank" in data.columns:
            data = data.sort_values("rank", ascending=True)
        elif "score" in data.columns:
            data = data.sort_values("score", ascending=False)
        start = max(int(offset), 0)
        size = min(max(int(limit), 1), 500)
        return {
            "records": data.iloc[start : start + size],
            "total": int(len(data)),
            "offset": start,
            "limit": size,
        }

    def data_freshness(self) -> list[dict[str, Any]]:
        import config

        items = [
            ("ranking", "最新排名", getattr(config, "RANKING_LATEST_PATH", "")),
            ("metrics", "模型指标", getattr(config, "METRICS_PATH", "")),
            ("raw_data", "最新行情", getattr(config, "LATEST_RAW_DATA_PATH", "")),
            ("feature_data", "最新特征", getattr(config, "LATEST_FEATURE_DATA_PATH", "")),
            ("news", "新闻缓存", getattr(config, "NEWS_CACHE_PATH", "")),
            ("announcement", "公告缓存", getattr(config, "ANNOUNCEMENT_CACHE_PATH", "")),
            ("rag_documents", "RAG 文档", getattr(config, "RAG_DOCUMENTS_PATH", "")),
            ("rag_index", "RAG 索引", getattr(config, "RAG_INDEX_PATH", "")),
            ("backtest_nav", "回测净值", getattr(config, "BACKTEST_NAV_PATH", "")),
        ]
        rows: list[dict[str, Any]] = []
        for key, label, raw_path in items:
            path = Path(raw_path)
            exists = bool(raw_path) and path.exists()
            stat = path.stat() if exists else None
            rows.append(
                {
                    "key": key,
                    "label": label,
                    "status": "ready" if exists else "missing",
                    "updated_at": (
                        datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat()
                        if stat is not None
                        else None
                    ),
                    "size_bytes": int(stat.st_size) if stat is not None and path.is_file() else None,
                }
            )
        return rows

    def stock_detail(self, stock_code: str) -> dict[str, Any]:
        from application.dashboard_service import dashboard_service

        code = str(stock_code).zfill(6)
        ranking = self.ranking()
        ranking_record: dict[str, Any] = {}
        if ranking is not None and not getattr(ranking, "empty", True) and "code" in ranking.columns:
            found = ranking[ranking["code"].astype(str).str.zfill(6) == code]
            if not found.empty:
                ranking_record = found.iloc[0].to_dict()
        raw = dashboard_service.load_latest_raw_data()
        market_record: dict[str, Any] = {}
        if raw is not None and not getattr(raw, "empty", True) and "code" in raw.columns:
            found = raw[raw["code"].astype(str).str.zfill(6) == code]
            if not found.empty:
                if "date" in found.columns:
                    found = found.sort_values("date")
                market_record = found.iloc[-1].to_dict()
        events = dashboard_service.load_news_events_for_app()
        event_count = 0
        if events is not None and not getattr(events, "empty", True) and "code" in events.columns:
            event_count = int((events["code"].astype(str).str.zfill(6) == code).sum())
        return {
            "stock_code": code,
            "name": ranking_record.get("name") or market_record.get("name") or "",
            "ranking": ranking_record,
            "market": market_record,
            "event_count": event_count,
            "found": bool(ranking_record or market_record),
        }

    def stock_history(self, stock_code: str, *, limit: int = 120) -> dict[str, Any]:
        from application.dashboard_service import dashboard_service

        code = str(stock_code).zfill(6)
        frame = dashboard_service.load_latest_raw_data()
        if frame is None or getattr(frame, "empty", True) or "code" not in frame.columns:
            return {"stock_code": code, "records": [], "total": 0}
        data = frame[frame["code"].astype(str).str.zfill(6) == code].copy()
        if "date" in data.columns:
            data = data.sort_values("date")
        size = min(max(int(limit), 1), 1000)
        data = data.tail(size)
        return {"stock_code": code, "records": data, "total": int(len(data))}

    def stock_evidence(self, stock_code: str, *, query: str = "", top_k: int = 10) -> dict[str, Any]:
        from application.dashboard_service import dashboard_service

        code = str(stock_code).zfill(6)
        search_query = self._text(query) or f"{code} 最新新闻 公告 风险"
        try:
            frame = dashboard_service.retrieve_stock_context(
                code,
                search_query,
                top_k=min(max(int(top_k), 1), 50),
                force_rebuild=False,
            )
            return {"stock_code": code, "query": search_query, "records": frame, "total": int(len(frame))}
        except Exception as exc:
            return {
                "stock_code": code,
                "query": search_query,
                "records": [],
                "total": 0,
                "warning": type(exc).__name__,
            }

    def stock_explanation(self, stock_code: str) -> dict[str, Any]:
        from llm_explainer import load_cached_ai_explanation

        detail = self.stock_detail(stock_code)
        source = dict(detail.get("ranking") or {})
        source.update({key: value for key, value in (detail.get("market") or {}).items() if key not in source})
        cached: Any = None
        if source:
            try:
                cached = load_cached_ai_explanation(source)
            except Exception:
                cached = None
        return {
            "stock_code": str(stock_code).zfill(6),
            "available": cached not in (None, "", {}),
            "cached": cached,
            "generated": False,
            "message": "阶段 6.2 只读取已有解释缓存，不触发 LLM 生成。",
        }

    def model_catalog(self) -> dict[str, Any]:
        from application.dashboard_service import dashboard_service

        frame = dashboard_service.load_model_zoo_table()
        return {"records": frame, "total": int(len(frame))}

    def model_search_results(self) -> dict[str, Any]:
        from application import model_search_service as service

        def table(path: Any) -> Any:
            try:
                return service.load_table_file(path)
            except Exception:
                return []

        return {
            "candidates": table(service.MODEL_CANDIDATES_PATH),
            "master_backtests": table(service.BACKTEST_MASTER_TABLE_PATH),
            "target_results": table(service.MODEL_SEARCH_RESULTS_PATH),
            "errors": table(service.MODEL_SEARCH_ERRORS_PATH),
            "selected_strategy": service.load_selected_strategy(),
            "discovery_report": service.load_model_discovery_report(),
            "read_only": True,
        }

    def backtest_bundle(self) -> dict[str, Any]:
        from application.dashboard_service import dashboard_service

        nav, metrics, trades, predictions = dashboard_service.load_backtest_outputs()
        return {
            "backtest_id": "latest",
            "available": nav is not None and not getattr(nav, "empty", True),
            "metrics": metrics or {},
            "equity": nav if nav is not None else [],
            "trades": trades if trades is not None else [],
            "predictions": predictions if predictions is not None else [],
        }

    def news_events(
        self,
        *,
        stock_code: str | None = None,
        event_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        from application.dashboard_service import classify_event_title, dashboard_service

        frame = dashboard_service.load_news_events_for_app()
        if frame is None or getattr(frame, "empty", True):
            return {"records": [], "total": 0, "offset": int(offset), "limit": int(limit)}
        data = frame.copy()
        if "code" in data.columns:
            data["code"] = data["code"].astype(str).str.zfill(6)
        if stock_code and "code" in data.columns:
            data = data[data["code"] == str(stock_code).zfill(6)]
        if "date" in data.columns:
            parsed = data["date"].map(lambda value: str(value)[:10])
            if start_date:
                data = data[parsed >= str(start_date)]
                parsed = data["date"].map(lambda value: str(value)[:10])
            if end_date:
                data = data[parsed <= str(end_date)]
        normalized_type = self._text(event_type).lower()
        if normalized_type and normalized_type not in {"all", "全部"} and "title" in data.columns:
            def label(title: Any) -> str:
                flags = classify_event_title(str(title or "")) or {}
                if int(flags.get("is_risk_event") or 0) > 0:
                    return "risk"
                if int(flags.get("is_negative_event") or 0) > 0:
                    return "negative"
                if int(flags.get("is_positive_event") or 0) > 0:
                    return "positive"
                return "neutral"
            labels = data["title"].map(label)
            data = data[labels == normalized_type]
        sort_cols = [name for name in ("publish_time", "date") if name in data.columns]
        if sort_cols:
            data = data.sort_values(sort_cols, ascending=False)
        total = int(len(data))
        start = max(int(offset), 0)
        size = min(max(int(limit), 1), 500)
        data = data.iloc[start : start + size].copy()
        records = data.to_dict(orient="records")
        for record in records:
            record["event_id"] = self._event_id(record)
        return {"records": records, "total": total, "offset": start, "limit": size}

    def news_event(self, event_id: str) -> dict[str, Any] | None:
        page = self.news_events(limit=500)
        for record in page["records"]:
            if record.get("event_id") == event_id:
                return record
        return None

    def public_settings(self) -> dict[str, Any]:
        import config
        from local_config import load_local_config

        cfg = load_local_config()
        mode = self._text(cfg.get("llm_mode") or "api")
        model = self._text(
            cfg.get("llm_local_model") if mode == "local" else cfg.get("llm_api_model")
        )
        base_url = self._text(
            cfg.get("llm_local_base_url") if mode == "local" else cfg.get("llm_api_base_url")
        )
        api_key_configured = bool(self._text(cfg.get("llm_api_key"))) if mode == "api" else True
        return {
            "universe": self._text(getattr(config, "UNIVERSE", "")),
            "model_backend": self._text(cfg.get("model_backend")),
            "model_version": self._text(cfg.get("model_version") or "latest"),
            "default_topk": int(getattr(config, "TOPK", 10) or 10),
            "current_user_id": self._text(cfg.get("current_user_id") or "default"),
            "feature_flags": {
                "news": bool(getattr(config, "ENABLE_NEWS_FEATURES", False)),
                "rag": bool(getattr(config, "ENABLE_RAG", False)),
                "llm_explainer": bool(getattr(config, "ENABLE_LLM_EXPLAINER", False)),
            },
            "credentials": {
                "tushare_configured": bool(self._text(cfg.get("tushare_token"))),
                "llm_configured": bool(model and base_url and api_key_configured),
            },
            "llm": {
                "mode": mode,
                "provider": self._text(cfg.get("llm_api_provider")) if mode == "api" else "ollama",
                "model": model,
                "endpoint_configured": bool(base_url),
                "profile_id": self._text(
                    cfg.get("llm_local_profile_id") if mode == "local" else cfg.get("llm_api_profile_id")
                ),
            },
            "scheduler": {
                "enabled": bool(cfg.get("auto_retrain_enabled")),
                "hour": int(cfg.get("auto_retrain_hour") or 0),
                "minute": int(cfg.get("auto_retrain_minute") or 0),
            },
            "read_only": True,
        }

    def monitor_summary(self, *, user_id: str = "default") -> dict[str, Any]:
        from application.system_monitor_service import build_system_monitor_snapshot

        result = build_system_monitor_snapshot(user_id=str(user_id or "default"))
        return result.to_dict() if hasattr(result, "to_dict") else dict(result or {})

    def monitor_services(self, *, user_id: str = "default") -> dict[str, Any]:
        from application.system_monitor_service import (
            build_handoff_health_summary,
            build_memory_store_health_summary,
            build_message_bus_health_summary,
            build_react_health_summary,
            build_reflection_health_summary,
        )

        def safe(callable_obj: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                value = callable_obj(**kwargs)
                return value if isinstance(value, dict) else {"status": "ok", "value": value}
            except TypeError:
                try:
                    value = callable_obj()
                    return value if isinstance(value, dict) else {"status": "ok", "value": value}
                except Exception as exc:
                    return {"status": "unavailable", "error": type(exc).__name__}
            except Exception as exc:
                return {"status": "unavailable", "error": type(exc).__name__}

        return {
            "message_bus": safe(build_message_bus_health_summary, user_id=user_id),
            "memory": safe(build_memory_store_health_summary, user_id=user_id),
            "react": safe(build_react_health_summary, user_id=user_id),
            "reflection": safe(build_reflection_health_summary, user_id=user_id),
            "handoff": safe(build_handoff_health_summary, user_id=user_id),
        }

    def monitor_history(self, *, user_id: str = "default", limit: int = 30) -> list[dict[str, Any]]:
        from application.system_monitor_service import list_system_monitor_history

        return list_system_monitor_history(user_id=str(user_id or "default"), limit=min(max(int(limit), 1), 200))

    def monitor_alerts(self, *, user_id: str = "default", limit: int = 100) -> list[dict[str, Any]]:
        from application.system_monitor_service import list_system_monitor_alerts

        return list_system_monitor_alerts(user_id=str(user_id or "default"), limit=min(max(int(limit), 1), 500))


web_read_service = WebReadApplicationService()

__all__ = ["WebReadApplicationService", "web_read_service"]
