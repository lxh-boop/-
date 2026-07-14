from __future__ import annotations

from html import escape
from typing import Any


COMPACT_METRIC_STYLE = """
<style>
.compact-metric-card {
    padding: 0.30rem 0.45rem;
    min-height: 3rem;
    border: 1px solid rgba(49, 51, 63, 0.14);
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.72);
    overflow: visible;
}
.compact-metric-label {
    font-size: 0.75rem;
    line-height: 1.1;
    color: #5f6368;
    white-space: normal;
    overflow: visible;
    text-overflow: clip;
}
.compact-metric-value {
    font-size: 1.05rem;
    line-height: 1.15;
    font-weight: 600;
    margin-top: 0.16rem;
    white-space: nowrap;
    overflow: visible;
    text-overflow: clip;
}
</style>
"""


def build_compact_metric_html(label: str, value: str, help_text: str | None = None) -> str:
    title = f' title="{escape(help_text)}"' if help_text else ""
    return (
        f'<div class="compact-metric-card"{title}>'
        f'<div class="compact-metric-label">{escape(str(label or ""))}</div>'
        f'<div class="compact-metric-value">{escape(str(value or ""))}</div>'
        "</div>"
    )


def render_compact_metric(label: str, value: str, help_text: str | None = None, streamlit_module: Any | None = None) -> str:
    html = build_compact_metric_html(label, value, help_text)
    if streamlit_module is not None:
        streamlit_module.markdown(COMPACT_METRIC_STYLE + html, unsafe_allow_html=True)
    else:
        try:
            import streamlit as st

            st.markdown(COMPACT_METRIC_STYLE + html, unsafe_allow_html=True)
        except Exception:
            pass
    return html

