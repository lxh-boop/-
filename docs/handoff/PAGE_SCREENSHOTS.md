# Page Screenshots

本文档记录当前 APP 页面截图，方便后续接手者确认入口和页面大致状态。截图生成时间：2026-06-16。

## 截图文件

| 页面 | 截图 |
|---|---|
| 首页 / 预测排名 | `../screenshots/home_prediction_ranking.png` |
| AI 模拟盘 | `../screenshots/ai_paper_trading.png` |
| AI Agent | `../screenshots/ai_agent.png` |

## 生成方式

APP 当前运行方式：

```powershell
streamlit run app.py --server.port 8501 --server.address 127.0.0.1
```

截图通过本机 Chrome 和 Playwright 访问以下地址生成：

```text
http://127.0.0.1:8501
```

## 页面入口实现

- 顶层页面路由：`app.py`
- AI 模拟盘页面：`app/pages/ai_paper_trading.py`
- AI Agent 页面：`app/pages/ai_agent.py`
- 模型搜索页面：`app/pages/model_search.py`

## 使用说明

截图只用于交接和视觉确认，不作为业务数据源。真实数据请以 `DATA_SOURCE_OF_TRUTH.md` 和 `DATA_DICTIONARY.md` 中的文件为准。
