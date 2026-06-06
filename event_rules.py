POSITIVE_KEYWORDS = [
    "业绩预增",
    "业绩增长",
    "扭亏",
    "回购",
    "中标",
    "签订合同",
    "股东增持",
    "增持",
    "分红",
    "高送转",
    "战略合作",
]

NEGATIVE_KEYWORDS = [
    "业绩预亏",
    "业绩下降",
    "亏损",
    "下修",
    "减持",
    "解禁",
    "终止",
    "违约",
]

RISK_KEYWORDS = [
    "诉讼",
    "仲裁",
    "处罚",
    "监管函",
    "立案调查",
    "退市风险",
    "风险警示",
    "其他风险警示",
    "风险提示",
    "异常波动",
    "股票交易异常波动",
    "问询函",
    "警示函",
]

SPECIFIC_EVENT_RULES = {
    "has_earnings_positive": ["业绩预增", "业绩增长", "扭亏", "盈利增加"],
    "has_earnings_negative": ["业绩预亏", "业绩下降", "亏损", "业绩下滑"],
    "has_shareholder_reduce": ["减持"],
    "has_shareholder_increase": ["增持"],
    "has_lawsuit": ["诉讼", "仲裁"],
    "has_penalty": ["处罚", "监管函", "警示函", "立案调查", "问询函"],
    "has_merger": ["并购", "重组", "收购", "重大资产"],
    "has_buyback": ["回购"],
    "has_contract_win": ["中标", "签订合同", "项目合同"],
}


def contains_any(text: str, keywords: list[str]) -> bool:
    text = str(text or "")
    return any(keyword in text for keyword in keywords)


def classify_event_title(title: str) -> dict:
    title = str(title or "")
    result = {
        "is_positive_event": int(contains_any(title, POSITIVE_KEYWORDS)),
        "is_negative_event": int(contains_any(title, NEGATIVE_KEYWORDS)),
        "is_risk_event": int(contains_any(title, RISK_KEYWORDS)),
    }

    for flag, keywords in SPECIFIC_EVENT_RULES.items():
        result[flag] = int(contains_any(title, keywords))

    return result
