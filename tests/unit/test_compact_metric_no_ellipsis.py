from app.components.compact_metric import COMPACT_METRIC_STYLE, build_compact_metric_html


def test_compact_metric_no_ellipsis() -> None:
    html = build_compact_metric_html("cash", "150,000.00")

    assert "150,000.00" in html
    assert "ellipsis" not in html.lower()
    assert "text-overflow: clip" in COMPACT_METRIC_STYLE

