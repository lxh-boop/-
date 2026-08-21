from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable
from uuid import NAMESPACE_URL, uuid5

from database.repositories import (
    PortfolioRepository,
    PredictionRepository,
    RecommendationRepository,
    RuntimeDataImportAuditRepository,
    RuntimeStateRepository,
    UserRepository,
)
from portfolio.cash_flow import cash_flow_from_dict
from portfolio.paper_account import account_from_dict
from portfolio.storage import PortfolioStorage
from portfolio.trading_permissions import normalize_trading_permissions


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return [dict(row) for row in csv.DictReader(stream)]


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _audit_id(source_kind: str, digest: str) -> str:
    return "import_" + uuid5(
        NAMESPACE_URL,
        f"runtime-import|{source_kind}|{digest}",
    ).hex[:24]


def _run_import(
    *,
    source_kind: str,
    path: Path,
    db_path: str | Path | None,
    row_count: int,
    importer: Callable[[], int],
    force: bool,
    dry_run: bool,
    expected_import_count: int | None = None,
) -> dict[str, Any]:
    digest = _sha256(path)
    audit_repo = RuntimeDataImportAuditRepository(db_path)
    existing = audit_repo.find(source_kind, digest)
    if (
        existing
        and str(existing.get("validation_status") or "") == "validated"
        and not force
    ):
        return {
            "source_kind": source_kind,
            "source_path": str(path),
            "status": "already_imported",
            "source_rows": int(existing.get("source_row_count") or 0),
            "imported_rows": int(existing.get("imported_row_count") or 0),
            "sha256": digest,
        }
    expected = int(
        row_count if expected_import_count is None else expected_import_count
    )
    if dry_run:
        return {
            "source_kind": source_kind,
            "source_path": str(path),
            "status": "validated_dry_run",
            "source_rows": int(row_count),
            "expected_import_rows": expected,
            "imported_rows": 0,
            "sha256": digest,
        }

    imported = int(importer())
    if imported != expected:
        raise RuntimeError(
            f"runtime_import_count_mismatch:{source_kind}:"
            f"source={row_count}:expected={expected}:imported={imported}"
        )
    audit_repo.upsert(
        {
            "import_id": _audit_id(source_kind, digest),
            "source_kind": source_kind,
            "source_path": str(path.resolve()),
            "source_sha256": digest,
            "source_row_count": int(row_count),
            "imported_row_count": imported,
            "validation_status": "validated",
            "details": {
                "count_match": True,
                "expected_import_count": expected,
                "skipped_source_rows": int(row_count) - expected,
            },
            "imported_at": _now(),
        }
    )
    return {
        "source_kind": source_kind,
        "source_path": str(path),
        "status": "imported",
        "source_rows": int(row_count),
        "expected_import_rows": expected,
        "imported_rows": imported,
        "sha256": digest,
    }


def import_ranking_file(
    path: str | Path,
    *,
    db_path: str | Path | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    source = Path(path)
    rows = _read_csv(source)
    return _run_import(
        source_kind="ranking_latest",
        path=source,
        db_path=db_path,
        row_count=len(rows),
        importer=lambda: len(
            PredictionRepository(db_path).replace_snapshot(
                rows,
                source_kind="ranking",
            )
        ),
        force=force,
        dry_run=dry_run,
    )


def import_recommendation_file(
    path: str | Path,
    *,
    user_id: str,
    db_path: str | Path | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    source = Path(path)
    rows = _read_csv(source)
    scoped_rows = [
        row
        for row in rows
        if not str(row.get("user_id") or "").strip()
        or str(row.get("user_id") or "").strip() == str(user_id)
    ]
    if rows and not scoped_rows:
        raise ValueError(f"recommendation_owner_mismatch:{user_id}")
    return _run_import(
        source_kind=f"recommendations_latest:{user_id}",
        path=source,
        db_path=db_path,
        row_count=len(rows),
        importer=lambda: len(
            RecommendationRepository(db_path).replace_snapshot(user_id, scoped_rows)
        ),
        force=force,
        dry_run=dry_run,
        expected_import_count=len(scoped_rows),
    )


def _portfolio_importers(
    *,
    user_id: str,
    root: Path,
    db_path: str | Path | None,
) -> list[tuple[str, Path, list[Any], Callable[[], int]]]:
    repo = PortfolioRepository(db_path)
    storage = PortfolioStorage(db_path, output_dir=root, use_database=True)
    output: list[tuple[str, Path, list[Any], Callable[[], int]]] = []

    account_path = next(
        (path for path in [root / "paper_account_latest.json", root / "paper_account.json"] if path.is_file()),
        None,
    )
    if account_path:
        raw = _read_json(account_path)
        rows = [raw]
        account = account_from_dict(raw)
        output.append(
            (
                f"paper_account:{user_id}",
                account_path,
                rows,
                lambda account=account: int(bool(repo.insert_paper_account(account.to_dict()))),
            )
        )

    positions_path = next(
        (path for path in [root / "paper_positions_latest.csv", root / "paper_positions.csv"] if path.is_file()),
        None,
    )
    if positions_path:
        raw_rows = _read_csv(positions_path)
        positions = [storage._position_from_record(row) for row in raw_rows]
        output.append(
            (
                f"paper_positions:{user_id}",
                positions_path,
                raw_rows,
                lambda positions=positions: len(
                    repo.replace_positions(
                        user_id,
                        [item.to_database_record() for item in positions],
                    )
                ),
            )
        )

    orders_path = root / "paper_orders.csv"
    if orders_path.is_file():
        raw_rows = _read_csv(orders_path)
        eligible_rows = [
            row
            for row in raw_rows
            if str(row.get("action") or "").strip().lower()
            in {"buy", "sell", "hold", "reduce"}
        ]
        orders = [storage._order_from_record(row) for row in eligible_rows]
        output.append(
            (
                f"paper_orders:{user_id}",
                orders_path,
                raw_rows,
                lambda orders=orders: len(
                    repo.replace_paper_orders(
                        user_id,
                        [item.to_dict() for item in orders],
                    )
                ),
            )
        )

    nav_path = root / "paper_nav_latest.csv"
    if nav_path.is_file():
        rows = _read_csv(nav_path)
        output.append(
            (
                f"paper_nav:{user_id}",
                nav_path,
                rows,
                lambda rows=rows: sum(1 for row in rows if repo.insert_nav_record(row)),
            )
        )

    settings_path = root / "paper_trading_settings.json"
    if settings_path.is_file():
        raw = dict(_read_json(settings_path) or {})
        raw.setdefault("user_id", user_id)
        raw.setdefault("settings_id", f"paper_trading_settings_{user_id}_default")
        output.append(
            (
                f"paper_settings:{user_id}",
                settings_path,
                [raw],
                lambda raw=raw: int(bool(repo.upsert_trading_settings(raw))),
            )
        )

    risk_path = next(
        (path for path in [root / "portfolio_risk_report_latest.json", root / "portfolio_risk_report.json"] if path.is_file()),
        None,
    )
    if risk_path:
        raw = dict(_read_json(risk_path) or {})
        as_of_date = str(raw.get("as_of_date") or raw.get("trade_date") or _now()[:10])
        risk_record = {
            "risk_snapshot_id": "risk_snapshot_" + uuid5(
                NAMESPACE_URL,
                f"runtime-risk|{user_id}|{as_of_date}",
            ).hex[:24],
            "user_id": user_id,
            "account_id": str(raw.get("account_id") or f"paper_{user_id}"),
            "as_of_date": as_of_date,
            "report": raw,
            "created_at": str(raw.get("created_at") or _now()),
            "updated_at": _now(),
        }
        output.append(
            (
                f"portfolio_risk:{user_id}",
                risk_path,
                [raw],
                lambda record=risk_record: int(bool(repo.upsert_risk_snapshot(record))),
            )
        )

    decisions_path = root / "ai_paper_decisions_latest.json"
    if decisions_path.is_file():
        rows = list(_read_json(decisions_path) or [])
        output.append(
            (
                f"paper_decisions:{user_id}",
                decisions_path,
                rows,
                lambda rows=rows: sum(1 for row in rows if repo.insert_paper_decision(row)),
            )
        )

    diagnostics_path = root / "paper_execution_diagnostics_latest.json"
    if diagnostics_path.is_file():
        raw = dict(_read_json(diagnostics_path) or {})
        output.append(
            (
                f"paper_diagnostics:{user_id}",
                diagnostics_path,
                [raw],
                lambda raw=raw: int(
                    bool(
                        RuntimeStateRepository(db_path).put(
                            "paper_execution_diagnostics",
                            raw,
                            user_id=user_id,
                            scope_id=f"paper_{user_id}",
                        )
                    )
                ),
            )
        )

    flows_path = root / "paper_cash_flows.csv"
    if flows_path.is_file():
        raw_rows = _read_csv(flows_path)
        flows = [cash_flow_from_dict(row) for row in raw_rows]
        output.append(
            (
                f"paper_cash_flows:{user_id}",
                flows_path,
                raw_rows,
                lambda flows=flows: sum(
                    1 for flow in flows if repo.insert_cash_flow(flow.to_dict())
                ),
            )
        )
    return output


def import_portfolio_directory(
    root: str | Path,
    *,
    user_id: str,
    db_path: str | Path | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for kind, path, rows, importer in _portfolio_importers(
        user_id=str(user_id),
        root=Path(root),
        db_path=db_path,
    ):
        expected_import_count = len(rows)
        if kind.startswith("paper_orders:"):
            expected_import_count = sum(
                1
                for row in rows
                if str(row.get("action") or "").strip().lower()
                in {"buy", "sell", "hold", "reduce"}
            )
        results.append(
            _run_import(
                source_kind=kind,
                path=path,
                db_path=db_path,
                row_count=len(rows),
                importer=importer,
                force=force,
                dry_run=dry_run,
                expected_import_count=expected_import_count,
            )
        )
    return results


def import_user_profile_file(
    path: str | Path,
    *,
    user_id: str,
    db_path: str | Path | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    source = Path(path)
    raw = dict(_read_json(source) or {})
    user = str(user_id or raw.get("user_id") or "default")

    def importer() -> int:
        repo = UserRepository(db_path)
        repo.insert_user_profile(
            {
                "user_id": user,
                "profile_type": str(raw.get("profile_type") or "稳健型"),
                "nickname": str(raw.get("nickname") or ""),
                "age_range": str(raw.get("age_range") or ""),
                "income_level": str(raw.get("income_level") or ""),
                "income_stability": str(raw.get("income_stability") or ""),
                "available_capital": float(raw.get("available_capital") or raw.get("initial_capital") or 0.0),
                "investment_experience": str(raw.get("investment_experience") or ""),
                "liquidity_need": str(raw.get("liquidity_need") or ""),
                "trading_permissions": normalize_trading_permissions(raw.get("trading_permissions")),
            }
        )
        return 1

    return _run_import(
        source_kind=f"user_profile:{user}",
        path=source,
        db_path=db_path,
        row_count=1,
        importer=importer,
        force=force,
        dry_run=dry_run,
    )


def import_reliability_state_file(
    path: str | Path,
    *,
    user_id: str,
    db_path: str | Path | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    source = Path(path)
    raw = dict(_read_json(source) or {})
    state = raw.get(str(user_id)) if isinstance(raw.get(str(user_id)), dict) else raw
    payload = dict(state or {})
    payload["user_id"] = str(user_id)
    return _run_import(
        source_kind=f"ai_reliability_state:{user_id}",
        path=source,
        db_path=db_path,
        row_count=1,
        importer=lambda: int(
            bool(
                RuntimeStateRepository(db_path).put(
                    "ai_reliability_state",
                    payload,
                    user_id=str(user_id),
                    as_of_date=str(payload.get("as_of_date") or ""),
                )
            )
        ),
        force=force,
        dry_run=dry_run,
    )


def import_runtime_output_tree(
    output_dir: str | Path,
    *,
    db_path: str | Path | None = None,
    users: list[str] | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = Path(output_dir)
    results: list[dict[str, Any]] = []
    ranking = root / "ranking_latest.csv"
    if ranking.is_file():
        results.append(
            import_ranking_file(
                ranking,
                db_path=db_path,
                force=force,
                dry_run=dry_run,
            )
        )

    recommendation = root / "recommendations" / "final_recommendations_latest.csv"
    portfolio_root = root / "portfolio"
    discovered = sorted(
        {path.name for path in portfolio_root.iterdir() if path.is_dir()}
        if portfolio_root.is_dir()
        else set()
    )
    selected_users = [str(item) for item in (users or discovered)]
    if recommendation.is_file():
        recommendation_rows = _read_csv(recommendation)
        embedded_users = sorted(
            {
                str(row.get("user_id") or "").strip()
                for row in recommendation_rows
                if str(row.get("user_id") or "").strip()
            }
        )
        recommendation_users = embedded_users or selected_users
        for user in recommendation_users:
            if users and user not in selected_users:
                continue
            results.append(
                import_recommendation_file(
                    recommendation,
                    user_id=user,
                    db_path=db_path,
                    force=force,
                    dry_run=dry_run,
                )
            )
    for user in selected_users:
        user_portfolio = portfolio_root / user
        if user_portfolio.is_dir():
            results.extend(
                import_portfolio_directory(
                    user_portfolio,
                    user_id=user,
                    db_path=db_path,
                    force=force,
                    dry_run=dry_run,
                )
            )
        profile_candidates = [
            root / "users" / user / "user_profile.json",
            user_portfolio / "user_profile.json",
        ]
        profile = next((path for path in profile_candidates if path.is_file()), None)
        if profile:
            results.append(
                import_user_profile_file(
                    profile,
                    user_id=user,
                    db_path=db_path,
                    force=force,
                    dry_run=dry_run,
                )
            )
        reliability_candidates = [
            root / "evaluation" / user / "evaluation" / "ai_reliability_state.json",
            root / "evaluation" / "ai_reliability_state.json",
        ]
        reliability = next(
            (
                path
                for path in reliability_candidates
                if path.is_file()
                and str(user) in dict(_read_json(path) or {})
            ),
            None,
        )
        if reliability:
            results.append(
                import_reliability_state_file(
                    reliability,
                    user_id=user,
                    db_path=db_path,
                    force=force,
                    dry_run=dry_run,
                )
            )
    failed = [row for row in results if row.get("status") not in {"imported", "already_imported", "validated_dry_run"}]
    return {
        "status": "failed" if failed else "validated",
        "dry_run": bool(dry_run),
        "result_count": len(results),
        "results": results,
    }
