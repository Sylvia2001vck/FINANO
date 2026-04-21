# 一键 AI 选股（FBTI）：实现逻辑与技术说明

本文档说明 **「AI 选股」** 页面（`/ai-fund-pick`）的后端管线、与大模型的交互方式，并**如实回答**：是否基于完整八字排盘、是否按「当日运势」量化选股、是否存在面向用户的「八字流式输出」等。

---

## 1. 功能定位与接口

| 项目 | 说明 |
|------|------|
| **前端路由** | `frontend/src/pages/AiFundPick/index.tsx` |
| **同步接口** | `POST /api/v1/agent/ai/fbti-select` |
| **流式接口** | `POST /api/v1/agent/ai/fbti-select/stream`（SSE） |
| **核心服务** | `backend/app/services/ai_fund_selector.py` |
| **路由编排** | `backend/app/modules/agent/router.py`（`fbti_ai_select_funds` / `fbti_ai_select_funds_stream`） |

前置条件：用户须已保存 **FBTI 四位码**（`POST /api/v1/user/fbti/test` 或等价流程），否则接口返回 400。

---

## 2. 端到端管线（四段式）

实现与文件内注释一致：**偏好归纳 → 随机抽样与规则排序 →（可选）合并估值 → 大模型终筛**。

```
run_fbti_ai_selection / iter_fbti_ai_selection_sse_events
    │
    ├─ ① infer_selection_preferences_with_ai
    │      输入：FBTI 归档（code/name/tags/blurb）、五行字符串 wuxing、
    │            时间标签 time_label（当前北京时间文案）
    │      输出：结构化偏好 JSON（risk_preference、preferred_tracks、
    │            emphasize_sharpe 等）
    │      失败：_default_preferences_from_arch（规则默认偏好）
    │
    ├─ ② _sample_and_rank_top_pool
    │      从目录随机至多 400 只 → 按 _score_fund_for_preferences 打分 → Top20
    │
    ├─ ③ _merge_live_quotes_if_applicable（可选）
    │      静态池且开启 FUND_LIVE_QUOTE_ENABLED 时为 Top20 合并估值字段
    │
    └─ ④ select_funds_with_ai
           将 Top20 瘦身快照 + 偏好摘要送入大模型，要求返回 JSON：
           { "reason": str, "funds": [ { code, name, wuxing_tag, change_hint } ] }
           失败：_pick_diverse_fallback_funds（规则从 Top20 取 5 只）
```

**大模型调用次数（云端链路正常时）：** 阶段 ①、④ 各 **1 次** `_invoke_finance_llm`（见 `ai_fund_selector._invoke_json_llm` → `llm_client._invoke_finance_llm`），共 **2 次**主要生成调用；与 MAFB 流水线相互独立。

---

## 3. 「五行 / 生日 / 运势」在代码里究竟是什么

### 3.1 是否有「完整八字排盘」？

**没有。** 本项目中与「命理」相关的部分均为 **工程化演示规则**，明确注释为非专业命理：

- `backend/app/services/bazi_wuxing.py`：`compute_today_wuxing_preference(birth, now)` 用公历生日数字种子 + **当前北京时间时辰** 映射到 **单字五行倾向**（规则表），**不是**四柱八字、大运流年等专业排盘。
- `backend/app/agent/profiling.py`：`day_master_demo` 等由生日 **确定性演示** 映射到日主天干等 **结构化字段**，用于报告与娱乐化 TOP5，**不构成传统命理结论**。

### 3.2 AI 选股主结果（至多 5 只基金）是否按「生日八字」逐条推算？

**不是。** 主路径 **`run_fbti_ai_selection`** 的输入核心是：

- **FBTI 人格归档**（`match_archetype`）：四位码、名称、标签、简介、归档上的 **五行字串**（`arch["wuxing"]` 等）。
- **五行字符串 `wuxing`**：来自用户 **`user.user_wuxing`**（个人画像保存时由 `fuse_wuxing` 融合 FBTI 归档五行与 `bazi_wuxing` 提示）或请求体覆盖，缺省则用归档五行。
- **`time_label`**：服务端 **`_fbti_time_label()`** 生成的 **「当前北京时间」可读字符串**，作为提示词里的「参考时间」，**并非**单独计算的「今日运势指数」或黄历 API。

基金打分 **`_score_fund_for_preferences`** 使用的是：**赛道/名称关键词** 与 **偏好 JSON**、**风险等级**、**夏普/回撤/动量** 等表字段，以及对 **`wuxing` 字符串中「金木水火土」** 与基金名称/赛道关键词的 **简单加分规则**（见 `ai_fund_selector.py` 中 `if "金" in wx:` 等分支）。  
这是 **可审计的启发式量化**，不是玄学理论的形式化证明。

### 3.3 「当日运势 → 量化指标 → 选基」是否成立？

**部分成立、且范围有限：**

- **「当日」**：仅体现在 **`time_label`（当前时刻文案）** 进入大模型 prompt，以及 `bazi_wuxing` 里 **时辰** 参与合成「喜用演示」五行（若用户有生日且流程写入 `user_wuxing`）。**没有**独立的「今日运势分」表或外部运势 API。
- **「量化」**：**有**——对候选基金使用 **数值字段**（`sharpe_3y`、`max_drawdown_3y`、`momentum_60d`、`risk_rating` 等）与规则打分；五行相关为 **少量加权项 + 关键词匹配**，与专业「命理量化」不是同一含义。

### 3.4 页面上的「个性化 TOP5（五行 / 流年 + 金融统计）」是什么？

同步与流式接口在返回主结果前会调用 **`_enrich_fbti_result_with_personalized`**：

- 使用 `build_user_profile(user_birth, mbti, …)`（生日缺省时用占位日期）得到结构化 `user_profile`（含 **dominant_element**、**liunian_2026** 等规则字段）。
- 用 `build_top5_personalized_entertainment`（`backend/app/agent/top5.py`）在 **全表基金** 上计算 **娱乐向** 综合分：金融统计项 + **日主五行与赛道映射** + **流年行业倾斜系数** 等 **写死在代码中的规则**。

该 **TOP5 与前面大模型选出的至多 5 只基金不是同一列表**；前端文案已标明为 **「趣味展示」**，与 MAFB 专业流水线解耦。

---

## 4. 流式输出（SSE）：用户「能看到什么」

### 4.1 后端

`iter_fbti_ai_selection_sse_events` **按阶段** `yield` 事件（非 LLM token 流）：

| 顺序 | `event` | `node` | 用户可见 `label`（约） |
|------|---------|--------|-------------------------|
| 1 | `stage` | `prefs` | 归纳选股偏好（大模型）… |
| 2 | `stage` | `pool` | 随机抽样与规则 Top20… |
| 3 | `stage` | `quotes` | 合并估值数据（若开启）… |
| 4 | `stage` | `llm` | 大模型终筛至多 5 只… |
| 5 | `result` | — | 完整 JSON：`reason`、`funds`，并经 `_enrich` 附加 `personalized_top5` |

路由 `fbti_ai_select_funds_stream` 将上述事件封装为 **SSE**（`text/event-stream`）。

### 4.2 前端

`postFbtiAiSelectStream`（`frontend/src/services/fbti.ts`）解析 `data:` 行：对 **`event === "stage"`** 调用 `onStage(node, label)`；**一键 AI 选股** 按钮加载中时，页面展示 **`aiStage` 字符串**（即上表中的中文阶段说明）。

### 4.3 明确「没有」什么流式能力

- **没有** 大模型 **逐字 / 逐 token** 的流式输出（当前实现为单次 `Generation` 式调用，整段 JSON 返回后再解析）。
- **没有** 单独的 **「八字分析报告」** SSE 通道；若需展示「命理相关」文字，主要来自：
  - 最终 JSON 里的 **`reason`**（模型或规则生成的说明），以及
  - **`personalized_top5`** 每行的 **`reason_mingli_structured` / `reason_finance`**（规则拼接字符串）。

---

## 5. 大模型适配层（与 MAFB 共用）

- 调用链：`ai_fund_selector._invoke_json_llm` → `llm_client._invoke_finance_llm`。
- **人设**：`FINANCE_EXPERT_SYSTEM_PROMPT` 注入（见 `llm_client.py`）。
- **路由**：DashScope → DeepSeek → Ollama →（`MAFB_LLM_MODE=auto` 时）本地 Qwen 等，与 MAFB 一致。
- **解析**：用正则抽取首个 `{...}` JSON；缺字段或解析失败则走规则分支，并尽量在 `reason` 中给出可操作的失败说明。

---

## 6. 合规与产品表述建议

- 本功能在代码与 UI 中均应以 **「演示 / 娱乐 / 不构成投资建议」** 为底线表述。
- 若对外宣传，应避免声称「根据真实八字与当日运势精确选基」；宜表述为：**FBTI 行为金融画像 + 规则化五行娱乐维度 + 基金表字段量化 + 大模型在缩小候选后的语义终筛**，并区分 **主选 5 只** 与 **趣味 TOP5**。

---

## 7. 关键文件索引

| 路径 | 作用 |
|------|------|
| `backend/app/services/ai_fund_selector.py` | 选股主逻辑、SSE 生成器、两阶段 JSON LLM |
| `backend/app/modules/agent/router.py` | `/agent/ai/fbti-select`、`/stream`、个性化 enrichment |
| `backend/app/agent/top5.py` | `build_top5_personalized_entertainment` 娱乐 TOP5 |
| `backend/app/agent/profiling.py` | `build_user_profile`（生日/MBTI/流年规则字段） |
| `backend/app/services/bazi_wuxing.py` | 生日 + 时辰的简化五行演示 |
| `backend/app/agent/llm_client.py` | 统一金融 LLM 调用 |
| `frontend/src/pages/AiFundPick/index.tsx` | 一键按钮、阶段文案、`personalized_top5` 表格 |
| `frontend/src/services/fbti.ts` | `postFbtiAiSelectStream` SSE 客户端 |

---

*文档版本：与仓库实现一致；若后续增加真实八字流式或独立运势服务，请同步修订本节。*
