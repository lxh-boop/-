# A 股每日股票评分与滚动训练 APP

本项目用于机器学习、金融数据分析和项目展示：基于 A 股日线数据构造特征，训练或接入外部模型，生成每日股票评分排名，并在 Streamlit APP 中展示预测排名、模型指标、回测结果、模型搜索结果、新闻映射和 AI 解释。

免责声明：本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。回测结果仅代表历史数据上的模型表现，不代表未来收益，不构成投资建议。

## 功能概览

- CSI300 股票池与本地行情缓存
- Alpha158 MLP、LightGBM、External DFT_UNET、Chronos-Bolt、MOMENT 等模型后端
- 每日增量更新与下一交易日预测排名
- TopK 展示、个股详情、风险等级、可信度和概率校准
- T+1 回测、净值曲线、每日收益 CSV 和模型结果汇总表
- 全网模型搜索、候选模型分类、目标模式汇总
- DeepSeek / OpenAI-compatible AI 解释，支持生成并编辑 Prompt
- 新闻事件映射、RAG 检索与解释依据模块
- 单元测试、集成测试和基础 APP 测试

## 安装依赖

```powershell
cd D:\stock_daily_app
pip install -r requirements.txt
```

## 初始训练

```powershell
python train_model.py --source qlib
```

初始训练优先读取本地 Qlib / CSV 历史数据，生成 Alpha158 特征并保存模型到 `models/`。模型权重和本地数据默认不会上传到 GitHub。

## 每日增量更新

```powershell
python daily_incremental_update.py --token 你的TushareToken --base-version latest
```

每日更新会读取本地模型和行情缓存，按交易日拉取最近行情，必要时做增量微调，并生成 `outputs/ranking_latest.csv`。

## 模型搜索

```powershell
python scripts/model_search/discover_models.py --github-per-query 4 --hf-per-query 5 --arxiv-per-query 4
```

主要输出：

```text
outputs/model_discovery/model_candidates.csv
outputs/model_discovery/model_discovery_report.md
outputs/model_discovery/errors.csv
```

## 统一回测

```powershell
python scripts/evaluate/run_model_backtest.py --model-name chronos_bolt_small --topk 10,30,50 --holding-days 1 --backtest-days 60
```

主要输出：

```text
outputs/backtests/daily_returns/
outputs/backtests/predictions/
outputs/backtests/backtest_master_table.csv
```

## 目标模式搜索

```powershell
python scripts/model_search/target_search.py --target-metric annual_return --target-value 0.10 --max-candidates 50 --min-days 60
```

目标是寻找历史回测达到指定指标的候选方案，不代表未来收益，也不是收益承诺。

## 启动 APP

```powershell
streamlit run app.py
```

APP 支持：

- 配置 Tushare Token、AI API Key、Base URL 和 Model
- 选择模型后端和模型库方案
- 生成每日预测排名
- 查看 TopK 排名、个股详情、模型指标和回测分析
- 查看模型搜索与回测结果，选择默认方案
- 生成、编辑 Prompt，并调用真实大模型生成解释

## 本地文件说明

以下目录主要保存本地运行产物，已通过 `.gitignore` 排除：

```text
data/
models/
outputs/
logs/
external_repos/
```

如需复现实验，请按 README 中的训练、更新和回测命令重新生成本地数据与模型文件。

## 目录结构

详见 `PROJECT_STRUCTURE.md`。
