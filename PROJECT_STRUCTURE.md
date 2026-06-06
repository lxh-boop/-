# Project Structure

当前项目采取渐进式整理：保留旧入口，新增功能逐步放入 `app/`、`core/`、`scripts/` 等目录，保证原命令仍可运行。

```text
stock_daily_app/
├── app/
│   ├── pages/
│   │   └── model_search.py
│   ├── services/
│   │   ├── file_loader.py
│   │   └── model_search_results.py
│   └── components/
├── core/
│   ├── config/
│   │   └── paths.py
│   └── search/
│       ├── discovery.py
│       └── target_search.py
├── scripts/
│   ├── evaluate/
│   │   └── run_model_backtest.py
│   ├── model_search/
│   │   ├── discover_models.py
│   │   └── target_search.py
│   └── test/
├── model_discovery/
├── model_backends/
├── model_zoo/
├── external_models/
├── news_mapping/
├── tests/
├── data/
├── models/
├── outputs/
├── logs/
├── app.py
├── train_model.py
├── daily_incremental_update.py
├── requirements.txt
└── README.md
```

## Current Entry Points

```text
app.py
    Streamlit APP 入口，继续支持 streamlit run app.py。

train_model.py
    初始训练入口，继续支持 python train_model.py --source qlib。

daily_incremental_update.py
    每日增量更新入口，继续支持 python daily_incremental_update.py --token xxx --base-version latest。

auto_model_search.py
    模型搜索兼容入口，继续支持 python auto_model_search.py --target-metric annual_return --target-value 0.10 --max-trials 20。

scripts/model_search/discover_models.py
    模型候选发现 wrapper，核心能力在 core/search/discovery.py。

scripts/model_search/target_search.py
    目标模式搜索 wrapper，核心能力在 core/search/target_search.py。

scripts/evaluate/run_model_backtest.py
    统一模型回测脚本。
```

## Runtime Outputs

```text
outputs/model_discovery/model_candidates.csv
    全网候选模型表。

outputs/backtests/backtest_master_table.csv
    所有统一回测结果汇总表。

outputs/backtests/daily_returns/
    每个模型 / TopK 的每日收益 CSV。

outputs/model_search/search_results.csv
    按目标指标汇总后的模型搜索结果。

outputs/model_search/selected_strategy.json
    APP 当前选择的默认回测方案。
```

这些运行产物默认不提交到 GitHub，需要在本地运行训练、更新、搜索或回测命令重新生成。

## Disclaimer

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。回测结果仅代表历史数据上的模型表现，不代表未来收益，不构成投资建议。
