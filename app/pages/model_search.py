from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from application.model_search_service import (
    BACKTEST_DISCLAIMER,
    BACKTEST_MASTER_TABLE_PATH,
    MODEL_CANDIDATES_PATH,
    MODEL_SEARCH_ERRORS_PATH,
    MODEL_SEARCH_RESULTS_PATH,
    format_strategy_option,
    load_daily_returns_for_strategy,
    load_model_discovery_report,
    load_selected_strategy,
    load_table_file,
    make_strategy_from_row,
    resolve_output_path,
    save_selected_strategy,
)


def render_model_search_page() -> None:
    st.subheader("模型搜索与回测结果")
    st.warning(BACKTEST_DISCLAIMER)
    st.caption("这里汇总全网候选模型、已完成回测和目标搜索结果；所有结果只用于历史评估和项目展示。")

    candidates_df = load_table_file(MODEL_CANDIDATES_PATH)
    master_df = load_table_file(BACKTEST_MASTER_TABLE_PATH)
    search_results_df = load_table_file(MODEL_SEARCH_RESULTS_PATH)
    search_errors_df = load_table_file(MODEL_SEARCH_ERRORS_PATH)
    selected_strategy = load_selected_strategy()

    successful_master = pd.DataFrame()
    if not master_df.empty and "status" in master_df.columns:
        successful_master = master_df[master_df["status"].astype(str).str.lower() == "success"].copy()

    target_hit_count = 0
    if not search_results_df.empty and "target_hit" in search_results_df.columns:
        target_hit_count = int(search_results_df["target_hit"].astype(str).str.lower().eq("true").sum())

    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
    metric_col1.metric("候选模型", len(candidates_df))
    metric_col2.metric("成功回测", len(successful_master))
    metric_col3.metric("目标达标", target_hit_count)
    metric_col4.metric("默认方案", selected_strategy.get("model_name", "未选择") if selected_strategy else "未选择")

    if selected_strategy:
        with st.expander("当前默认方案", expanded=True):
            st.json(selected_strategy)

    st.markdown("#### 候选模型")
    if candidates_df.empty:
        st.info("暂无候选模型表，请先运行模型搜索脚本。")
    else:
        candidate_show = candidates_df.copy()
        category_options = ["全部"] + sorted(
            candidate_show.get("category", pd.Series(dtype=str)).dropna().astype(str).unique().tolist()
        )
        category_filter = st.selectbox("候选模型分类", options=category_options, key="model_search_category_filter")
        if category_filter != "全部" and "category" in candidate_show.columns:
            candidate_show = candidate_show[candidate_show["category"].astype(str) == category_filter].copy()
        candidate_cols = [
            "candidate_id",
            "model_name",
            "category",
            "source_type",
            "source_url",
            "has_pretrained_weight",
            "has_training_code",
            "dependency_risk",
            "windows_compatibility",
            "priority",
            "status",
            "notes",
        ]
        candidate_cols = [col for col in candidate_cols if col in candidate_show.columns]
        st.dataframe(candidate_show[candidate_cols].head(200), width="stretch")

    with st.expander("查看模型搜索报告"):
        discovery_report = load_model_discovery_report()
        if discovery_report:
            st.markdown(discovery_report)
        else:
            st.info("暂无模型搜索报告。")

    st.markdown("#### 回测汇总")
    if master_df.empty:
        st.info("暂无统一回测汇总表，请先运行模型回测。")
    else:
        master_show = master_df.copy()
        if "annual_return" in master_show.columns:
            master_show["annual_return_num"] = pd.to_numeric(master_show["annual_return"], errors="coerce")
            master_show = master_show.sort_values("annual_return_num", ascending=False)

        completed_only = st.checkbox("只看成功回测", value=True, key="model_search_success_only")
        if completed_only and "status" in master_show.columns:
            master_show = master_show[master_show["status"].astype(str).str.lower() == "success"].copy()

        model_options = ["全部"]
        if "model_name" in master_show.columns:
            model_options.extend(sorted(master_show["model_name"].dropna().astype(str).unique().tolist()))
        selected_model_filter = st.selectbox("回测模型", options=model_options, key="model_search_model_filter")
        if selected_model_filter != "全部" and "model_name" in master_show.columns:
            master_show = master_show[master_show["model_name"].astype(str) == selected_model_filter].copy()

        master_cols = [
            "run_id",
            "model_name",
            "model_category",
            "topk",
            "holding_days",
            "rank_by",
            "start_date",
            "end_date",
            "num_days",
            "annual_return",
            "cum_return",
            "sharpe",
            "max_drawdown",
            "win_rate",
            "IC",
            "RankIC",
            "target_hit",
            "status",
            "fail_reason",
        ]
        master_cols = [col for col in master_cols if col in master_show.columns]
        st.dataframe(master_show[master_cols].head(200), width="stretch")

    st.markdown("#### 目标搜索结果")
    if search_results_df.empty:
        st.info("暂无 target_search 结果。")
    else:
        results_show = search_results_df.copy()
        if "annual_return" in results_show.columns:
            results_show["annual_return_num"] = pd.to_numeric(results_show["annual_return"], errors="coerce")
            results_show = results_show.sort_values("annual_return_num", ascending=False)
        if "target_hit" in results_show.columns:
            hit_only = st.checkbox("只看达到目标的历史回测", value=False, key="target_hit_only")
            if hit_only:
                results_show = results_show[results_show["target_hit"].astype(str).str.lower() == "true"].copy()
        result_cols = [
            "run_id",
            "model_name",
            "model_category",
            "topk",
            "holding_days",
            "annual_return",
            "cum_return",
            "sharpe",
            "max_drawdown",
            "target_hit",
            "daily_returns_csv",
        ]
        result_cols = [col for col in result_cols if col in results_show.columns]
        st.dataframe(results_show[result_cols].head(200), width="stretch")

        selectable_results = results_show.copy()
        if not selectable_results.empty:
            selectable_results = selectable_results.reset_index(drop=True)
            option_map = {
                format_strategy_option(row): idx
                for idx, row in selectable_results.iterrows()
            }
            selected_option = st.selectbox(
                "选择一个方案作为 APP 默认方案",
                options=list(option_map.keys()),
                key="selected_strategy_option",
            )
            selected_row = selectable_results.iloc[option_map[selected_option]]
            selected_row_strategy = make_strategy_from_row(selected_row)

            action_col1, action_col2 = st.columns([1, 3])
            with action_col1:
                if st.button("保存为默认方案", type="primary", key="save_selected_strategy"):
                    save_selected_strategy(selected_row_strategy)
                    st.success("默认方案已保存。")
                    st.rerun()
            with action_col2:
                daily_returns_path = resolve_output_path(selected_row_strategy.get("daily_returns_csv"))
                if daily_returns_path and daily_returns_path.exists():
                    st.download_button(
                        "下载该方案每日收益 CSV",
                        data=daily_returns_path.read_bytes(),
                        file_name=daily_returns_path.name,
                        mime="text/csv",
                        key="download_strategy_daily_returns",
                    )
                else:
                    st.info("该方案没有可下载的每日收益 CSV。")

            daily_returns_df = load_daily_returns_for_strategy(selected_row_strategy)
            if daily_returns_df.empty:
                st.info("该方案暂无可绘制的每日收益数据。")
            else:
                nav_col = "nav" if "nav" in daily_returns_df.columns else "cum_return"
                fig_strategy_nav = px.line(
                    daily_returns_df,
                    x="date",
                    y=nav_col,
                    title="所选方案历史净值曲线",
                )
                st.plotly_chart(fig_strategy_nav, width="stretch")

    if not search_errors_df.empty:
        with st.expander("查看搜索/训练/回测错误记录"):
            st.dataframe(search_errors_df, width="stretch")
