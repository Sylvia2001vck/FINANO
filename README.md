# Finano

Finano 是企业轻量标准的全栈金融演示项目：`React 18 + TypeScript + Vite` 前端（Axios 统一拦截、全局 Loading、401 跳转登录、Zustand 用户态），`FastAPI + SQLAlchemy 2.0 + JWT` 后端；开发/演示默认 **SQLite**，生产可选 **MySQL**（Docker Compose），**不使用 Alembic**（小项目 `create_all` 即可）。

## 企业技术选型（刻意不用的组件）

| 不用 | 原因 | 本项目替代 |
|------|------|------------|
| Alembic | 单人/演示/内网工具改表不频繁 | `Base.metadata.create_all` |
| Celery + Redis | 小规模 OCR/抓取同步接口更稳 | 同步 FastAPI 路由 |
| Chroma | 依赖重、易踩坑 | **FAISS-CPU** 轻量向量检索 |
| TA-Lib | 跨平台编译问题多 | **Pandas** 指标与相似度计算 |

**基金代码识图**：安装 **EasyOCR**（`pip install -r requirements-optional-easyocr.txt`）后，`POST /api/v1/ocr/fund-code` 使用 `readtext(..., detail=0)` 抽取 **6 位代码**（如 `005827`），返回 `codes` 与 **`primary_code`（首个候选）**；未安装时返回明确安装提示。

**真实行情扩展**：设置环境变量 **`FUND_LIVE_QUOTE_ENABLED=true`** 后，`get_fund_by_code` 在静态演示池基础上合并 **东方财富/天天基金** 估值 JSONP（`app/services/fund_data.py`，失败自动忽略）。启动时自动 **`DROP TABLE IF EXISTS comments`**，清理旧版评论表，无需手删库（仍可与删库重建并用）。

## Finano AI：MAFB（多智能体金融决策大脑）— 报告可直接引用

- **定位**：LangGraph **0.2.18** 多智能体 + **DashScope Qwen-Finance / 通用**（云端优先）+ **Qwen-1.8B CPU**（本地兜底）+ **FAISS** RAG + 命理/画像结构化特征（MBTI、生日、环境偏好、风险偏好等），输出 **TOP5、推理链、仓位建议** 等强制 JSON。
- **智能体角色**：User Profiling → **Fundamental / Technical / Risk / K线相似**（四路并行）→ Allocation → Compliance → 投票决策。
- **核心接口**（均需登录）：
  - `POST /api/v1/agent/run` — MAFB 流水线（`use_saved_profile`）
  - `GET/POST /api/v1/agent/profile` — 用户档案画像
  - `GET /api/v1/agent/funds` — 演示基金池（`FUND_LIVE_QUOTE_ENABLED=true` 时每只基金可带 `live_quote`，含 `gzjs`/`gszzl`/`gssj` 等；首次请求会因限流略慢）
  - `GET /api/v1/agent/funds/similar` — **Pandas 相似基金**（演示池静态特征）
  - `GET /api/v1/agent/funds/kline-similar` — **K 线/净值序列相似**（东方财富历史净值 `lsjz`，近 N 日对齐日收益率，余弦或 DTW）
  - `POST /api/v1/agent/ocr-birth` — 生日 OCR（百度等，见原有逻辑）
  - `POST /api/v1/ocr/fund-code` — **EasyOCR 仅抽 6 位基金代码**
  - `GET/POST /api/v1/community/posts` — 社区 **发帖 + 点赞**（无评论接口）
- **数据库**：用户表含 `mbti、birth_date、layout_facing、risk_preference`；启动时删除遗留 **`comments`** 表（若存在）。若仍有其它历史表结构冲突，可删除 `finano.db` 后重启。

**简历表述示例**：基于通义千问金融 API 与 LangGraph 状态编排实现多智能体协同；FAISS RAG + 强制 JSON 投票；**云端与本地 Qwen-1.8B 双链路容灾**；前置合规拦截与可解释推理链输出。

## 项目结构

```text
finano/
├── frontend/          # React 前端
├── backend/           # FastAPI 后端
├── docker-compose.yml
├── .env.example
└── README.md
```

## 已实现模块

- 用户注册、登录、JWT 鉴权
- 交易记录增查、统计汇总
- 交割单 OCR 导入
- AI 交易分析
- **MAFB 多智能体基金管线（LangGraph + FAISS RAG + 合规网关）**
- 复盘笔记
- 热点新闻演示数据
- 社区发帖与点赞
- Docker Compose（MySQL + backend + frontend，无 Redis/Celery）

### MAFB（Multi-Agent Fund Brain）双轨说明

- **工程轨**：登录、交易、笔记、热点、社区、OCR 识码、相似基金、Docker。
- **智能体轨**：`backend/app/agent/` — 画像、基本面、技术面、风控、合规、配置与投票；**FAISS** RAG；**LangGraph** 状态共享。
- **前端路由**：`/mafb` 多智能体控制台、`/profile` 用户档案、`/ocr-fund` 基金代码识图、`/similar-funds` 相似对比、`/community` 社区。

## 工程说明

- 本地默认 **SQLite**；Docker 使用 **MySQL**。
- 指标与相似度：**Pandas / NumPy**，不用 TA-Lib。
- AI / OCR：无 Key 或缺依赖时有明确降级与提示，保证可演示。

## 本地启动

### 1. 后端

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
# 国内网络若超时，可使用清华镜像：
# pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
# 基金代码 EasyOCR（可选，体积较大）：
# pip install -r requirements-optional-easyocr.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
uvicorn app.main:app --reload
```

### MAFB 金融大模型（云端主力 + 本地容灾）

- **主力（有网）**：`DASHSCOPE_API_KEY` + **`FINANCE_MODEL_NAME`（优先）** 或 `QWEN_FINANCE_MODEL`；代码内已注入**金融专家系统提示词**（通用强模型 + 专业 Prompt）。**DashScope 优先**；失败时可经 **Tongyi / DeepSeek / Ollama**。
- **离线降级（无 API、演示不翻车）**：`MAFB_LLM_MODE=auto` 时，云端全失败后自动切换 **`LOCAL_FINANCE_MODEL_ID` 本地 Qwen-1.8B 系权重（CPU）**，见 `backend/app/agent/local_qwen.py`。安装额外依赖：
  ```bash
  pip install -r requirements-optional-local-llm.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
  ```
  默认权重 ID 为 `Qwen/Qwen1.8B-Chat`；若你有社区 **Qwen-1.8B-Finance** 微调仓库，直接改 `LOCAL_FINANCE_MODEL_ID` 即可。
- **纯本地演示**：`MAFB_LLM_MODE=local_only`（不请求任何云 API）。
- **规则兜底**：未装 torch 或模型加载失败时，分析师与合规仍走 **确定性规则引擎**。
- **简历表述建议**：基于通义千问金融 API 构建多智能体推理核心，并实现 **云端 API 与本地开源 Qwen-1.8B 系权重双链路容灾**，低温结构化 JSON 输出支撑 Agent 投票与合规审查。

后端文档地址：`http://localhost:8000/docs`

### 2. 前端

```bash
cd frontend
npm install
npm run dev
```

前端地址：`http://localhost:5173`

## Docker 启动

```bash
copy .env.example .env
docker-compose up --build
```

## 演示建议流程

1. 注册并登录系统
2. 在交易记录页新增一笔交易或上传交割单图片
3. 在仪表盘查看收益曲线与核心指标
4. 在 **个人画像** 保存 MBTI / 生日 / 风险偏好，再在 **MAFB** 勾选「使用已保存画像」运行流水线，查看 **TOP5 + 推理链 + 仓位建议**
5. 在 AI 页面选择交易生成复盘分析
6. 在复盘笔记页补充总结
7. 在 **OCR 识图** 页上传含代码的截图，或 **相似基金** 页输入代码对比；在社区页发帖、点赞

## 测试

```bash
cd backend
pip install -r requirements.txt
pytest tests/test_mafb_graph.py -v   # LangGraph 全链路 + 并行 fan-out + 合规/投票字段断言
pytest tests/test_fund_data.py -v   # 天天基金 JSONP 解析（无网也可跑）
pytest
```
