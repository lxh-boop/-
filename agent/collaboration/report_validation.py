"""Grounding and scope validation for the W06 final report.

The validator works only with sanitized upstream WorkerResult payloads. It does
not query providers, mutate state, or invent missing entities. Its job is to
prevent the report LLM from turning a display request into risk analysis,
strategy advice, or unsupported entity claims.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable


_CODE_KEYS = {
    "public_code",
    "security_code",
    "stock_code",
    "symbol",
    "code",
    "exchange_symbol",
    "ts_code",
}
_LABEL_KEYS = {
    "display_label",
    "security_name",
    "stock_name",
    "display_name",
}
_RISK_OUTPUT_TYPES = {"PortfolioRiskResult"}
_STRATEGY_OUTPUT_TYPES = {"ReviewedProposal"}
_IMPACT_OUTPUT_TYPES = {"EntityAnalysisResult"}

_RISK_REQUEST_MARKERS = (
    "风险",
    "回撤",
    "集中度",
    "适配",
    "权限",
    "波动",
    "暴露",
    "稳健",
)
_ADVICE_REQUEST_MARKERS = (
    "建议",
    "调整",
    "调仓",
    "优化",
    "推荐",
    "操作",
    "买入",
    "卖出",
    "怎么办",
)
_ANALYSIS_REQUEST_MARKERS = ("分析", "评价", "诊断", "影响", "原因", "解释")
_VIEW_REQUEST_MARKERS = ("查看", "查询", "显示", "列出", "当前", "状态", "持仓", "账户")
_PORTFOLIO_SCOPE_MARKERS = ("持仓", "组合", "仓位", "模拟盘")
_ADJUSTMENT_REQUEST_MARKERS = (
    "怎么调整",
    "如何调整",
    "应该怎么调整",
    "持仓调整",
    "调整持仓",
    "调仓",
    "优化持仓",
    "优化组合",
    "仓位建议",
    "持仓建议",
    "增减仓",
)
_VIEW_SCOPE_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        r"(?:^|\n)\s*(?:#{1,6}\s*)?(?:关键观察|风险提示|风险分析|投资建议|操作建议)",
        "scope_violation",
    ),
    (
        r"(?:^|\n)\s*(?:#{1,6}\s*)?(?:近期交易记录|订单明细|交易明细|策略执行(?:情况|逻辑)?)",
        "unrequested_detail_scope",
    ),
    (
        r"风险可控|抗风险能力|行业分散性(?:良好|较好)|持仓结构(?:稳健|合理)|整体(?:稳健|安全)|资产增值良好|策略执行逻辑清晰",
        "scope_violation",
    ),
    (
        r"(?:表明|说明|意味着).{0,35}(?:风险|波动|稳健|合理|安全|策略|影响)",
        "unsupported_inference",
    ),
    (
        r"未来可探索|建议持续|建议关注|建议考虑|可考虑|应当调整|推荐(?:买入|卖出|持有)",
        "advice_scope_violation",
    ),
)

_ADVICE_PATTERNS: tuple[str, ...] = (
    r"(?:^|\n)\s*(?:#{1,6}\s*)?(?:投资建议|操作建议|调仓建议|买卖建议)",
    r"建议(?:增加|降低|买入|卖出|持有|增仓|减仓|调仓|调整(?:仓位|持仓)|替换|移除)",
    r"建议(?:持续)?关注(?:该股|该证券|该公司|市场风险|价格风险)",
    r"可考虑(?:买入|卖出|调整|调仓|增持|减持)",
    r"应当(?:买入|卖出|调整|调仓|增持|减持)",
    r"推荐(?:买入|卖出|持有)",
)

_CAUSAL_PATTERNS: tuple[str, ...] = (
    r"(?:新闻|公告|事件).{0,30}(?:导致|造成|驱动|促使)",
    r"由于.{0,40}(?:因此|从而).{0,40}(?:买入|卖出|上涨|下跌|调整)",
)

_CODE_PATTERN = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_POSITION_ID_PATTERN = re.compile(r"(?:^|_)(\d{6})$")
_NODE_ID_PATTERN = re.compile(r"(?:^|:)(\d{6})$")
_TABLE_NAME_PATTERN = re.compile(r"^[\u4e00-\u9fffA-Za-z·（）()\-]{2,30}$")
_PAREN_CODE_NAME = re.compile(
    r"(?P<name>[\u4e00-\u9fffA-Za-z·\-]{2,30})\s*[（(]\s*(?P<code>\d{6})\s*[）)]"
)
_CODE_PAREN_NAME = re.compile(
    r"(?P<code>\d{6})\s*[（(]\s*(?P<name>[\u4e00-\u9fffA-Za-z·\-]{2,30})\s*[）)]"
)


@dataclass(frozen=True)
class AuthoritativeEntity:
    code: str
    labels: tuple[str, ...] = ()
    entity_ref: str = ""
    source: str = ""
    locked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "public_code": self.code,
            "allowed_display_labels": list(self.labels),
            "entity_ref": self.entity_ref,
            "source": self.source,
            "locked": self.locked,
        }


@dataclass(frozen=True)
class ReportPolicy:
    objective: str
    view_only: bool
    risk_requested: bool
    advice_requested: bool
    adjustment_requested: bool
    risk_available: bool
    strategy_available: bool
    impact_available: bool
    output_types: tuple[str, ...]
    entities: tuple[AuthoritativeEntity, ...] = ()

    @property
    def entity_map(self) -> dict[str, set[str]]:
        return {item.code: set(item.labels) for item in self.entities}

    def to_prompt_dict(self) -> dict[str, Any]:
        if self.view_only:
            allowed_scope = [
                "账户和持仓的已验证状态",
                "上游已经计算好的数值",
                "数据时间与明确限制",
            ]
        else:
            allowed_scope = ["仅限用户目标及上游专业 Worker 已提供的结论"]
        return {
            "objective": self.objective,
            "view_only": self.view_only,
            "risk_requested": self.risk_requested,
            "advice_requested": self.advice_requested,
            "adjustment_requested": self.adjustment_requested,
            "risk_worker_result_available": self.risk_available,
            "strategy_worker_result_available": self.strategy_available,
            "impact_worker_result_available": self.impact_available,
            "available_output_types": list(self.output_types),
            "authoritative_entities": [item.to_dict() for item in self.entities],
            "allowed_scope": allowed_scope,
        }


@dataclass(frozen=True)
class ReportValidationIssue:
    code: str
    message: str
    evidence: str = ""
    repairable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "evidence": self.evidence,
            "repairable": self.repairable,
        }


@dataclass(frozen=True)
class ReportValidationResult:
    valid: bool
    issues: tuple[ReportValidationIssue, ...] = field(default_factory=tuple)

    @property
    def repairable(self) -> bool:
        return bool(self.issues) and all(item.repairable for item in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "repairable": self.repairable,
            "issues": [item.to_dict() for item in self.issues],
        }


def _normalize_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    match = _CODE_PATTERN.search(text)
    return match.group(1) if match else ""


def _clean_label(value: Any) -> str:
    label = " ".join(str(value or "").split()).strip("|：:;,，。")
    return label[:80]


def _walk(value: Any) -> Iterable[tuple[str, Any, dict[str, Any] | None]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key), item, value
            yield from _walk(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item)


def _entity_from_mapping(mapping: dict[str, Any]) -> tuple[str, str, str, str, bool]:
    code = ""
    label = ""
    entity_ref = ""
    source = str(mapping.get("source") or mapping.get("identity_source") or "")
    locked = bool(mapping.get("locked") or mapping.get("identity_locked"))
    for key in _CODE_KEYS:
        if key in mapping:
            code = _normalize_code(mapping.get(key))
            if code:
                break
    if not code:
        position_id = str(mapping.get("position_id") or "")
        match = _POSITION_ID_PATTERN.search(position_id)
        code = match.group(1) if match else ""
    graph_value = mapping.get("entity_ref") or mapping.get("security_ref") or mapping.get("graph_ref")
    if isinstance(graph_value, dict):
        entity_ref = str(graph_value.get("node_id") or "")
        if not code:
            match = _NODE_ID_PATTERN.search(entity_ref)
            code = match.group(1) if match else ""
        source = source or str(graph_value.get("source") or "")
        locked = locked or bool(graph_value.get("locked"))
    elif graph_value:
        entity_ref = str(graph_value)
    if not entity_ref:
        entity_ref = str(mapping.get("node_id") or "")
        if not code:
            match = _NODE_ID_PATTERN.search(entity_ref)
            code = match.group(1) if match else ""
    for key in _LABEL_KEYS:
        if key in mapping:
            label = _clean_label(mapping.get(key))
            if label:
                break
    return code, label, entity_ref, source, locked


def _collect_entities(safe_results: list[dict[str, Any]]) -> tuple[AuthoritativeEntity, ...]:
    labels_by_code: dict[str, set[str]] = {}
    locked_labels_by_code: dict[str, set[str]] = {}
    metadata: dict[str, dict[str, Any]] = {}
    seen_mappings: set[int] = set()
    for _, _, parent in _walk(safe_results):
        if not isinstance(parent, dict) or id(parent) in seen_mappings:
            continue
        seen_mappings.add(id(parent))
        code, label, entity_ref, source, locked = _entity_from_mapping(parent)
        if not code:
            continue
        labels_by_code.setdefault(code, set())
        locked_labels_by_code.setdefault(code, set())
        if label:
            labels_by_code[code].add(label)
            if locked:
                locked_labels_by_code[code].add(label)
        current = metadata.setdefault(code, {})
        if entity_ref:
            current["entity_ref"] = entity_ref
        if source:
            current["source"] = source
        current["locked"] = bool(current.get("locked") or locked)
    return tuple(
        AuthoritativeEntity(
            code=code,
            labels=tuple(
                sorted(
                    locked_labels_by_code.get(code)
                    or labels_by_code.get(code)
                    or set()
                )
            ),
            entity_ref=str(metadata.get(code, {}).get("entity_ref") or ""),
            source=str(metadata.get(code, {}).get("source") or ""),
            locked=bool(metadata.get(code, {}).get("locked")),
        )
        for code in sorted(labels_by_code)
    )


def _result_available(item: dict[str, Any]) -> bool:
    status = str(item.get("status") or "").strip().lower()
    payload = item.get("payload", item.get("data"))
    return status in {"completed", "partial", "proposal_ready"} and isinstance(payload, dict) and bool(payload)


def is_portfolio_adjustment_request(objective: str) -> bool:
    """Return whether the user asks for a concrete current-portfolio change plan.

    The plan is still unexecuted: W05 must produce ``ReviewedProposal`` and the
    later approval/revalidation boundary remains unchanged.
    """

    text = " ".join(str(objective or "").split())
    if not text:
        return False
    in_portfolio_scope = any(marker in text for marker in _PORTFOLIO_SCOPE_MARKERS)
    requests_adjustment = any(marker in text for marker in _ADJUSTMENT_REQUEST_MARKERS)
    return bool(in_portfolio_scope and requests_adjustment)


def build_report_policy(
    objective: str,
    safe_results: list[dict[str, Any]],
    *,
    request_mode: str = "",
    goal_contract: dict[str, Any] | None = None,
    authority_results: list[dict[str, Any]] | None = None,
) -> ReportPolicy:
    """Compile report scope from structured planning state when available.

    The compatibility fallback still supports older direct callers. Production
    W06 passes request_mode and goal_contract, so task scope is not inferred from
    free-form keyword matching.
    """

    text = " ".join(str(objective or "").split())
    available_results = [item for item in safe_results if _result_available(item)]
    output_types = tuple(
        sorted(
            {
                str(item.get("output_type") or "")
                for item in available_results
                if str(item.get("output_type") or "")
            }
        )
    )
    mode = str(request_mode or "").strip().lower()
    goal = dict(goal_contract or {})
    required_slots = {
        str(item) for item in goal.get("required_information_slots") or [] if str(item)
    }
    desired_types = {
        str(item) for item in goal.get("desired_output_types") or [] if str(item)
    }
    structured_scope = bool(mode or goal)
    if structured_scope:
        risk_requested = bool(
            "portfolio_risk_assessment" in required_slots
            or "portfolio_risk_constraints" in required_slots
            or "PortfolioRiskResult" in desired_types
        )
        advice_requested = bool(mode == "proposal" or "ReviewedProposal" in desired_types)
        adjustment_requested = bool(advice_requested and "reviewed_proposal" in required_slots)
        state_only_slots = {
            "account_financial_state",
            "current_portfolio_state",
            "portfolio_positions",
            "authoritative_holding_entities",
            "user_facing_report",
            "goal_completion_summary",
        }
        view_only = bool(
            mode == "analysis"
            and required_slots
            and required_slots.issubset(state_only_slots)
            and not risk_requested
            and not advice_requested
        )
    else:
        # Legacy compatibility only. New Agent execution passes structured scope.
        risk_requested = any(marker in text for marker in _RISK_REQUEST_MARKERS)
        adjustment_requested = is_portfolio_adjustment_request(text)
        advice_requested = adjustment_requested or any(marker in text for marker in _ADVICE_REQUEST_MARKERS)
        analysis_requested = any(marker in text for marker in _ANALYSIS_REQUEST_MARKERS)
        view_requested = any(marker in text for marker in _VIEW_REQUEST_MARKERS)
        view_only = bool(view_requested and not risk_requested and not advice_requested and not analysis_requested)
    entity_source = authority_results if authority_results is not None else available_results
    return ReportPolicy(
        objective=text,
        view_only=view_only,
        risk_requested=risk_requested,
        advice_requested=advice_requested,
        adjustment_requested=adjustment_requested,
        risk_available=bool(set(output_types) & _RISK_OUTPUT_TYPES),
        strategy_available=bool(set(output_types) & _STRATEGY_OUTPUT_TYPES),
        impact_available=bool(set(output_types) & _IMPACT_OUTPUT_TYPES),
        output_types=output_types,
        entities=_collect_entities(entity_source),
    )


def is_view_only_request(objective: str) -> bool:
    """Return whether the user asks only to display/query current state."""

    return build_report_policy(objective, []).view_only


def view_scope_expansion_text(value: str) -> str:
    """Return the first planner/report phrase that expands a view-only goal."""

    text = " ".join(str(value or "").split())
    patterns = (
        r"风险(?:分析|评价|提示|可控)",
        r"行业(?:分析|评价|判断|分散)",
        r"投资建议|操作建议|调仓建议|买卖建议",
        r"策略(?:分析|评价|建议|优化)",
        r"集中度|适配性|权限风险|影响分析",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    return ""


def _clean_reported_entity_label(value: Any) -> str:
    """Remove report action wording that may precede a parenthesized code.

    Natural Chinese recommendations often read ``维持紫金矿业（601899）``.
    The entity parser must compare ``紫金矿业`` with the authoritative label,
    not misclassify the action verb as part of the company name.
    """

    label = _clean_label(value)
    prefix = re.compile(
        r"^(?:(?:本报告(?:基于.{0,40})?|报告|结论)[:：\s，,]*)?"
        r"(?:(?:待审批调整预案|待审批预案|调整预案|调仓预案|调整建议|操作建议)[:：\s]*)?"
        r"(?:(?:建议|可考虑|应当|推荐)(?:将)?[:：\s]*)?"
        r"(?:(?:在.{0,30}?后)?重新发起对|聚焦于|聚焦|关于|针对|对|分析|研究|查看)?[:：\s]*"
        r"(?:维持|持有|保留|观察|增仓|减仓|增加|降低|买入|卖出|替换|移除|新增|调高|调低)?[:：\s]*"
    )
    previous = ""
    while label and label != previous:
        previous = label
        label = prefix.sub("", label).strip()
    return label


def _reported_entity_pairs(text: str) -> list[tuple[str, str, str]]:
    pairs: list[tuple[str, str, str]] = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if "|" in stripped:
            cells = [cell.strip().strip("`*") for cell in stripped.strip("|").split("|")]
            for index, cell in enumerate(cells):
                if not re.fullmatch(r"\d{6}", cell):
                    continue
                adjacent = []
                if index + 1 < len(cells):
                    adjacent.append(cells[index + 1])
                if index > 0:
                    adjacent.append(cells[index - 1])
                for candidate in adjacent:
                    candidate = _clean_label(candidate)
                    if _TABLE_NAME_PATTERN.fullmatch(candidate) and not re.search(
                        r"代码|名称|数量|价格|市值|占比|成本|证券", candidate
                    ):
                        pairs.append((cell, candidate, stripped[:200]))
                        break
        for pattern in (_PAREN_CODE_NAME, _CODE_PAREN_NAME):
            for match in pattern.finditer(stripped):
                pairs.append(
                    (
                        match.group("code"),
                        _clean_reported_entity_label(match.group("name")),
                        stripped[:200],
                    )
                )
    unique: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for code, label, evidence in pairs:
        key = (code, label)
        if key not in seen:
            seen.add(key)
            unique.append((code, label, evidence))
    return unique


def validate_report_output(answer: str, policy: ReportPolicy) -> ReportValidationResult:
    text = str(answer or "").strip()
    issues: list[ReportValidationIssue] = []
    if not text:
        issues.append(
            ReportValidationIssue(
                code="empty_report",
                message="报告正文为空。",
                repairable=True,
            )
        )
        return ReportValidationResult(valid=False, issues=tuple(issues))

    entity_map = policy.entity_map
    allowed_codes = set(entity_map)
    for code, label, evidence in _reported_entity_pairs(text):
        if code not in allowed_codes:
            issues.append(
                ReportValidationIssue(
                    code="unsupported_entity_code",
                    message=f"报告使用了上游未提供的证券代码 {code}。",
                    evidence=evidence,
                )
            )
            continue
        allowed_labels = entity_map.get(code) or set()
        if not allowed_labels:
            issues.append(
                ReportValidationIssue(
                    code="unsupported_entity_label",
                    message=f"证券 {code} 没有权威名称，报告不得自行补充“{label}”。",
                    evidence=evidence,
                )
            )
        elif label not in allowed_labels:
            issues.append(
                ReportValidationIssue(
                    code="entity_mismatch",
                    message=(
                        f"证券 {code} 的报告名称“{label}”与权威名称"
                        f"{sorted(allowed_labels)}不匹配。"
                    ),
                    evidence=evidence,
                )
            )

    if policy.view_only:
        for pattern, code in _VIEW_SCOPE_PATTERNS:
            match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
            if match:
                issues.append(
                    ReportValidationIssue(
                        code=code,
                        message="用户仅要求查看状态，W06 不得新增风险评价、行业判断或操作建议。",
                        evidence=match.group(0)[:200],
                    )
                )

    if not policy.risk_available:
        risk_match = re.search(
            r"风险可控|抗风险能力|风险水平(?:较低|较高)|集中度(?:合理|过高)|组合(?:稳健|安全)",
            text,
            flags=re.IGNORECASE,
        )
        if risk_match:
            issues.append(
                ReportValidationIssue(
                    code="missing_risk_worker_grounding",
                    message="报告包含风险结论，但上游没有 PortfolioRiskResult。",
                    evidence=risk_match.group(0)[:200],
                )
            )

    if not (policy.advice_requested and policy.strategy_available):
        for pattern in _ADVICE_PATTERNS:
            match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
            if match:
                issues.append(
                    ReportValidationIssue(
                        code="missing_strategy_worker_grounding",
                        message=(
                            "报告包含操作建议，但用户目标或上游 "
                            "ReviewedProposal 不支持该内容。"
                        ),
                        evidence=match.group(0)[:200],
                    )
                )
                break

    if not policy.impact_available:
        for pattern in _CAUSAL_PATTERNS:
            match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
            if match:
                issues.append(
                    ReportValidationIssue(
                        code="unsupported_causal_claim",
                        message="报告生成了因果影响结论，但上游没有 EntityAnalysisResult。",
                        evidence=match.group(0)[:200],
                    )
                )
                break

    # Goal-completion validation is separate from scope validation. A report may
    # contain no fabricated fact and still fail the user by omitting the requested
    # adjustment advice or by claiming that advice was never requested.
    if policy.adjustment_requested and not policy.risk_available:
        issues.append(
            ReportValidationIssue(
                code="missing_required_risk_worker_output",
                message="持仓调整方案需要上游 PortfolioRiskResult，但当前没有可用风险结果。",
                evidence="PortfolioRiskResult unavailable",
                repairable=False,
            )
        )
    if policy.advice_requested and not policy.strategy_available:
        issues.append(
            ReportValidationIssue(
                code="missing_required_strategy_worker_output",
                message="用户要求持仓调整方案，但当前没有可用的 ReviewedProposal。",
                evidence="ReviewedProposal unavailable",
                repairable=False,
            )
        )
    incorrect_intent = re.search(
        r"用户未请求.{0,24}(?:建议|调整|调仓)|因用户未请求.{0,24}(?:建议|调整|调仓)",
        text,
        flags=re.IGNORECASE,
    )
    if policy.advice_requested and incorrect_intent:
        issues.append(
            ReportValidationIssue(
                code="incorrect_user_intent_statement",
                message="报告错误声称用户没有请求调整建议。",
                evidence=incorrect_intent.group(0)[:200],
                repairable=True,
            )
        )
    if policy.advice_requested and policy.strategy_available:
        advice_content = re.search(
            r"增仓|减仓|调仓|调整方案|目标权重|建议权重|增加|降低|买入|卖出|持有|保留|维持|替换|移除|新增|观察",
            text,
            flags=re.IGNORECASE,
        )
        if not advice_content:
            issues.append(
                ReportValidationIssue(
                    code="goal_not_satisfied",
                    message="用户要求持仓调整方案，但报告没有呈现上游 ReviewedProposal 的调整结论。",
                    evidence=policy.objective[:200],
                    repairable=True,
                )
            )

        pending_boundary = re.search(
            r"待审批|待确认|尚未执行|未执行|需要确认|需确认|仅为预案",
            text,
            flags=re.IGNORECASE,
        )
        if policy.adjustment_requested and not pending_boundary:
            issues.append(
                ReportValidationIssue(
                    code="proposal_boundary_missing",
                    message="持仓调整回答必须明确这是待审批且尚未执行的 Proposal。",
                    evidence=policy.objective[:200],
                    repairable=True,
                )
            )
        execution_claim = re.search(
            r"已执行|已完成调仓|已完成调整|已经买入|已经卖出|持仓已调整",
            text,
            flags=re.IGNORECASE,
        )
        if execution_claim:
            issues.append(
                ReportValidationIssue(
                    code="unsupported_execution_claim",
                    message="当前上游只有 ReviewedProposal，报告不得声称已经执行持仓调整。",
                    evidence=execution_claim.group(0)[:200],
                    repairable=True,
                )
            )

    deduped: list[ReportValidationIssue] = []
    seen_issue: set[tuple[str, str]] = set()
    for issue in issues:
        key = (issue.code, issue.evidence)
        if key not in seen_issue:
            seen_issue.add(key)
            deduped.append(issue)
    return ReportValidationResult(valid=not deduped, issues=tuple(deduped))


__all__ = [
    "AuthoritativeEntity",
    "ReportPolicy",
    "ReportValidationIssue",
    "ReportValidationResult",
    "build_report_policy",
    "is_portfolio_adjustment_request",
    "is_view_only_request",
    "validate_report_output",
    "view_scope_expansion_text",
]
