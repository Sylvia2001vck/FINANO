# 多Agent并行

Gemini

Conversation with Gemini
帮我看看有没有真正实现多Agent和主从Agent """
Finance LLM adapter — 双链路容灾：

1. 主力：阿里云 DashScope 通义千问（模型名由 FINANCE_MODEL_NAME / QWEN_FINANCE_MODEL 配置）
+ 统一「金融专家」系统人设（通用强模型 + 专业 Prompt ≈ 金融垂直助手，无需单独 qwen-finance SKU）
2. 降级：DeepSeek、Ollama（与 DashScope 不同密钥/通道）
3. 再降级：本地开源 Qwen-1.8B 系 CPU 推理（见 local_qwen.py）
4. 再失败：由 nodes 规则引擎兜底，演示不翻车

说明：不再链接 LangChain Tongyi 作为 DashScope 后的回退——二者共用同一 API Key，
无效密钥时会重复 401 且 tenacity 打出冗长堆栈。

Qwen3 等多模态模型须走 **MultiModalConversation**（multimodal-generation）；纯文本模型仍用 **Generation**。
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import re
import threading
import time
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.dashscope_setup import apply_dashscope_settings
from app.agent.local_qwen import invoke_local_qwen_finance

logger = logging.getLogger(__name__)
_LLM_CONCURRENCY_GATE = threading.BoundedSemaphore(value=max(1, int(settings.mafb_llm_max_concurrency)))

# 通用模型 + 专业人设 = 金融分析助手（与 DashScope 控制台实际模型名配合使用）
FINANCE_EXPERT_SYSTEM_PROMPT = """你是一位专业、持牌、严谨的金融投资顾问。
你擅长基金分析、资产配置、风险控制、投资回报评估。
你必须遵守合规要求：不预测短期涨跌、不承诺收益、不提供具体交易时点，只做客观分析。
你输出内容必须专业、清晰、有数据支撑、结构化、可执行。
请以专业金融分析师的身份回答。"""

def _augment_messages_with_finance_persona(messages: list[dict[str, str]]) -> list[dict[str, str]]:
"""在首条 system 前叠加金融专家人设；若无 system 则插入一条。"""
prefix = FINANCE_EXPERT_SYSTEM_PROMPT.strip() + "\n\n"
out: list[dict[str, str]] = []
for m in messages:
out.append(dict(m))
if not out:
return [{"role": "system", "content": FINANCE_EXPERT_SYSTEM_PROMPT.strip()}]
if out[0].get("role") == "system":
out[0] = {
"role": "system",
"content": prefix + (out[0].get("content") or ""),
}
else:
out.insert(0, {"role": "system", "content": FINANCE_EXPERT_SYSTEM_PROMPT.strip()})
return out

class AgentScore(BaseModel):
agent_name: str = Field(description="智能体名称")
score: int = Field(ge=-2, le=2, description="打分 -2~+2")
reason: str = Field(description="中性、合规的金融推理理由，禁止承诺收益")

class ComplianceLLMResult(BaseModel):
"""合规 Agent 结构化输出；最终是否拦截仍由硬规则兜底。"""

allow_continue: bool = Field(description="是否允许进入最终组合输出")
compliance_score: int = Field(ge=-2, le=2, description="投教话术合规倾向分")
advisory_notes: str = Field(description="投教补充说明，避免违规表述")

def _extract_json_object(text: str) -> dict[str, Any]:
text = (text or "").strip()
m = re.search(r"\{[\s\S]*\}", text)
if not m:
raise ValueError("no json object in model output")
return json.loads(m.group())

def _parse_agent_score(raw: str, expected_name: str) -> AgentScore:
data = _extract_json_object(raw)
data.setdefault("agent_name", expected_name)
return AgentScore.model_validate(data)

def _compact_fund_for_llm(fund: dict[str, Any]) -> dict[str, Any]:
"""
仅保留打分必要字段，减少提示词体积与模型首包延迟。
"""
keep = (
"code",
"name",
"track",
"risk_rating",
"aum_billion",
"sharpe_3y",
"max_drawdown_3y",
"momentum_60d",
"volatility_60d",
"fee_rate",
)
out = {k: fund.get(k) for k in keep if k in fund}
if not out:
out = dict(fund or {})
return out

def _build_score_prompt(agent_role: str, fund: dict[str, Any], rag_chunks: list[str], user_risk: int) -> str:
rag = "\n".join(f"- {c}" for c in (rag_chunks or [])[:4])
fund_json = json.dumps(_compact_fund_for_llm(fund), ensure_ascii=False)
return f"""你是公募基金/ETF投研助手，仅基于给定结构化数据做事实性评估，不预测价格，不承诺收益。
角色：{agent_role}
用户风险等级(1-5)：{user_risk}
基金事实(JSON)：{fund_json}
RAG检索片段：
{rag}

请严格输出一个 JSON 对象，键为 agent_name, score, reason。
score 为整数 -2~+2（-2 强烈负面，+2 强烈正面）。
reason 用中文，中性表述，须包含「历史不代表未来」类风险提示意涵（可简短）。
agent_name 使用英文标识：fundamental / technical / risk 之一。
不要输出 JSON 以外的任何文字。"""

def _dashscope_model_uses_multimodal_api(model: str) -> bool:
"""与百炼文档一致：Qwen3 / VL / QVQ 等走 multimodal-generation，不能只用纯文本 Generation。"""
m = (model or "").strip().lower()
if not m:
return False
if "-vl" in m or m.startswith("qvq"):
return True
if "qwen3" in m:
return True
return False

def _dashscope_messages_to_multimodal(messages: list[dict[str, str]]) -> list[dict[str, Any]]:
"""MultiModalConversation：每条 content 为 [{\"text\": \"...\"}, ...]。"""
out: list[dict[str, Any]] = []
for m in messages:
role = str(m.get("role") or "user")
raw = m.get("content", "")
if isinstance(raw, list):
out.append({"role": role, "content": raw})
continue
text = "" if raw is None else str(raw)
out.append({"role": role, "content": [{"text": text}]})
return out

def _dashscope_extract_assistant_text(choice: Any) -> str:
"""兼容 Generation 与 MultiModalConversation 的 choices[0].message.content。"""
msg = getattr(choice, "message", None)
if msg is None:
return ""
content = getattr(msg, "content", None)
if content is None:
return ""
if isinstance(content, str):
return content
if isinstance(content, list):
parts: list[str] = []
for p in content:
if isinstance(p, dict) and p.get("text") is not None:
parts.append(str(p["text"]))
elif isinstance(p, str):
parts.append(p)
return "".join(parts)
if isinstance(content, dict):
t = content.get("text")
if t is not None:
return str(t)
return json.dumps(content, ensure_ascii=False)
return str(content)

def _invoke_dashscope(messages: list[dict[str, str]], model: str) -> str | None:
if not settings.dashscope_api_key:
return None
try:
import dashscope
except ImportError:
return None
apply_dashscope_settings(dashscope)
api_key = (settings.dashscope_api_key or "").strip()
try:
if _dashscope_model_uses_multimodal_api(model):
from dashscope import MultiModalConversation

mm_messages = _dashscope_messages_to_multimodal(messages)
response = MultiModalConversation.call(
api_key=api_key,
model=model,
messages=mm_messages,
result_format="message",
temperature=0.1,
max_tokens=512,
)
else:
response = dashscope.Generation.call(
api_key=api_key,
model=model,
messages=messages,
result_format="message",
temperature=0.1,
max_tokens=512,
)
code = getattr(response, "status_code", None)
if code is not None and code != 200:
logger.warning("DashScope error: %s", response)
return None
choices = getattr(getattr(response, "output", None), "choices", None) or []
if not choices:
logger.warning("DashScope empty choices: %s", response)
return None
text = _dashscope_extract_assistant_text(choices[0])
if not (text or "").strip():
logger.warning("DashScope empty assistant text: %s", response)
return None
return text.strip()
except Exception:
logger.exception("DashScope 调用失败 — 将尝试本地 Qwen-1.8B 降级")
return None

def _invoke_deepseek(messages: list[dict[str, str]]) -> str | None:
if not settings.deepseek_api_key:
return None
try:
import httpx
except ImportError:
return None
try:
r = httpx.post(
f"{settings.deepseek_api_base.rstrip('/')}/chat/completions",
headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
json={
"model": settings.deepseek_model,
"messages": messages,
"temperature": 0.1,
"max_tokens": 512,
},
timeout=min(28.0, max(8.0, float(settings.mafb_agent_llm_timeout_sec))),
)
r.raise_for_status()
data = r.json()
return data["choices"][0]["message"]["content"]
except Exception:
logger.exception("DeepSeek invocation failed")
return None

def _invoke_ollama(prompt: str) -> str | None:
if not settings.ollama_base_url or not settings.ollama_model:
return None
try:
import httpx
except ImportError:
return None
try:
r = httpx.post(
f"{settings.ollama_base_url.rstrip('/')}/api/generate",
json={"model": settings.ollama_model, "prompt": prompt, "stream": False},
timeout=min(28.0, max(8.0, float(settings.mafb_agent_llm_timeout_sec))),
)
r.raise_for_status()
return str(r.json().get("response") or "")
except Exception:
logger.exception("Ollama invocation failed")
return None

def _invoke_finance_llm(messages: list[dict[str, str]], prompt_fallback: str) -> str | None:
"""
DashScope（dashscope_finance_model）→ DeepSeek → Ollama → 本地 Qwen-1.8B；均失败则 None。
"""
mode = (settings.mafb_llm_mode or "auto").lower().strip()
messages_aug = _augment_messages_with_finance_persona(messages)
tongyi_prompt = f"{FINANCE_EXPERT_SYSTEM_PROMPT.strip()}\n\n{prompt_fallback}"

if mode == "local_only":
return (
invoke_local_qwen_finance(messages_aug, tongyi_prompt)
or _invoke_ollama(tongyi_prompt)
)

model = settings.dashscope_finance_model
raw: str | None = None
if mode in ("auto", "cloud_only"):
raw = _invoke_dashscope(messages_aug, model)
if raw is None and mode in ("auto", "cloud_only"):
raw = _invoke_deepseek(messages_aug)
if raw is None and mode in ("auto", "cloud_only"):
raw = _invoke_ollama(tongyi_prompt)

# 云端不可用或无 Key：自动切换本地 Qwen-1.8B 系（CPU，无需 API）
if raw is None and mode == "auto" and settings.local_finance_llm_enabled:
raw = invoke_local_qwen_finance(messages_aug, tongyi_prompt)
if raw:
logger.info("已使用本地 Qwen-1.8B 系权重完成推理（双链路容灾）")

return raw

def invoke_finance_agent_score(
agent_key: str,
agent_role_zh: str,
fund: dict[str, Any],
rag_chunks: list[str],
user_risk: int,
*,
llm_deadline_sec: float | None = None,
) -> AgentScore | None:
"""
返回结构化打分；若所有通道不可用或解析失败则返回 None，由调用方走规则引擎。
agent_key: fundamental | technical | risk

llm_deadline_sec：单次 LLM 链路上限（秒）；None 时用 settings.mafb_agent_llm_timeout_sec；≤0 表示不限制。
"""
prompt = _build_score_prompt(agent_role_zh, fund, rag_chunks, user_risk)
messages = [
{
"role": "system",
"content": "你只输出合法 JSON 对象，键为 agent_name, score, reason。",
},
{"role": "user", "content": prompt},
]

deadline = settings.mafb_agent_llm_timeout_sec if llm_deadline_sec is None else llm_deadline_sec
gate_enter_t0 = time.monotonic()
_LLM_CONCURRENCY_GATE.acquire()
gate_wait = time.monotonic() - gate_enter_t0
try:
if gate_wait > 0.2:
logger.info("Finance LLM 并发闸门等待 %.2fs（agent=%s）", gate_wait, agent_key)

if deadline and deadline > 0:
ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
try:
fut = ex.submit(_invoke_finance_llm, messages, prompt)
try:
raw = fut.result(timeout=float(deadline))
except concurrent.futures.TimeoutError:
logger.warning("Finance LLM 打分超时（%ss，agent=%s），将走规则引擎", deadline, agent_key)
raw = None
finally:
ex.shutdown(wait=False, cancel_futures=True)
else:
raw = _invoke_finance_llm(messages, prompt)
finally:
_LLM_CONCURRENCY_GATE.release()

if raw is None:
return None

try:
score = _parse_agent_score(raw, agent_key)
if score.agent_name != agent_key:
score = score.model_copy(update={"agent_name": agent_key})
return score
except Exception:
logger.warning("Failed to parse AgentScore from LLM output: %s", raw[:500])
return None

def invoke_compliance_llm(text_blob: str, fund_code: str) -> ComplianceLLMResult | None:
"""合规 Agent：大模型辅助审查话术；硬规则在 nodes 中仍优先。"""
system = (
"你是基金合规与投教审查助手。只输出 JSON，键为 allow_continue (bool), "
"compliance_score (-2~2 整数), advisory_notes (字符串)。"
"不得建议承诺收益或保本。若发现疑似违规营销，设 allow_continue=false。"
)
user = f"基金代码：{fund_code}\n待审查文本：\n{text_blob[:4000]}"
messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

raw = _invoke_finance_llm(messages, user)
if raw is None:
return None
try:
data = _extract_json_object(raw)
return ComplianceLLMResult.model_validate(data)
except Exception:
logger.warning("Failed to parse ComplianceLLMResult: %s", raw[:500])
return None
"""
Finance LLM adapter — 双链路容灾：

1. 主力：阿里云 DashScope 通义千问（模型名由 FINANCE_MODEL_NAME / QWEN_FINANCE_MODEL 配置）
+ 统一「金融专家」系统人设（通用强模型 + 专业 Prompt ≈ 金融垂直助手，无需单独 qwen-finance SKU）
2. 降级：DeepSeek、Ollama（与 DashScope 不同密钥/通道）
3. 再降级：本地开源 Qwen-1.8B 系 CPU 推理（见 local_qwen.py）
4. 再失败：由 nodes 规则引擎兜底，演示不翻车

说明：不再链接 LangChain Tongyi 作为 DashScope 后的回退——二者共用同一 API Key，
无效密钥时会重复 401 且 tenacity 打出冗长堆栈。

Qwen3 等多模态模型须走 **MultiModalConversation**（multimodal-generation）；纯文本模型仍用 **Generation**。
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import re
import threading
import time
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.dashscope_setup import apply_dashscope_settings
from app.agent.local_qwen import invoke_local_qwen_finance

logger = logging.getLogger(__name__)
_LLM_CONCURRENCY_GATE = threading.BoundedSemaphore(value=max(1, int(settings.mafb_llm_max_concurrency)))

# 通用模型 + 专业人设 = 金融分析助手（与 DashScope 控制台实际模型名配合使用）
FINANCE_EXPERT_SYSTEM_PROMPT = """你是一位专业、持牌、严谨的金融投资顾问。
你擅长基金分析、资产配置、风险控制、投资回报评估。
你必须遵守合规要求：不预测短期涨跌、不承诺收益、不提供具体交易时点，只做客观分析。
你输出内容必须专业、清晰、有数据支撑、结构化、可执行。
请以专业金融分析师的身份回答。"""

def _augment_messages_with_finance_persona(messages: list[dict[str, str]]) -> list[dict[str, str]]:
"""在首条 system 前叠加金融专家人设；若无 system 则插入一条。"""
prefix = FINANCE_EXPERT_SYSTEM_PROMPT.strip() + "\n\n"
out: list[dict[str, str]] = []
for m in messages:
out.append(dict(m))
if not out:
return [{"role": "system", "content": FINANCE_EXPERT_SYSTEM_PROMPT.strip()}]
if out[0].get("role") == "system":
out[0] = {
"role": "system",
"content": prefix + (out[0].get("content") or ""),
}
else:
out.insert(0, {"role": "system", "content": FINANCE_EXPERT_SYSTEM_PROMPT.strip()})
return out

class AgentScore(BaseModel):
agent_name: str = Field(description="智能体名称")
score: int = Field(ge=-2, le=2, description="打分 -2~+2")
reason: str = Field(description="中性、合规的金融推理理由，禁止承诺收益")

class ComplianceLLMResult(BaseModel):
"""合规 Agent 结构化输出；最终是否拦截仍由硬规则兜底。"""

allow_continue: bool = Field(description="是否允许进入最终组合输出")
compliance_score: int = Field(ge=-2, le=2, description="投教话术合规倾向分")
advisory_notes: str = Field(description="投教补充说明，避免违规表述")

def _extract_json_object(text: str) -> dict[str, Any]:
text = (text or "").strip()
m = re.search(r"\{[\s\S]*\}", text)
if not m:
raise ValueError("no json object in model output")
return json.loads(m.group())

def _parse_agent_score(raw: str, expected_name: str) -> AgentScore:
data = _extract_json_object(raw)
data.setdefault("agent_name", expected_name)
return AgentScore.model_validate(data)

def _compact_fund_for_llm(fund: dict[str, Any]) -> dict[str, Any]:
"""
仅保留打分必要字段，减少提示词体积与模型首包延迟。
"""
keep = (
"code",
"name",
"track",
"risk_rating",
"aum_billion",
"sharpe_3y",
"max_drawdown_3y",
"momentum_60d",
"volatility_60d",
"fee_rate",
)
out = {k: fund.get(k) for k in keep if k in fund}
if not out:
out = dict(fund or {})
return out

def _build_score_prompt(agent_role: str, fund: dict[str, Any], rag_chunks: list[str], user_risk: int) -> str:
rag = "\n".join(f"- {c}" for c in (rag_chunks or [])[:4])
fund_json = json.dumps(_compact_fund_for_llm(fund), ensure_ascii=False)
return f"""你是公募基金/ETF投研助手，仅基于给定结构化数据做事实性评估，不预测价格，不承诺收益。
角色：{agent_role}
用户风险等级(1-5)：{user_risk}
基金事实(JSON)：{fund_json}
RAG检索片段：
{rag}

请严格输出一个 JSON 对象，键为 agent_name, score, reason。
score 为整数 -2~+2（-2 强烈负面，+2 强烈正面）。
reason 用中文，中性表述，须包含「历史不代表未来」类风险提示意涵（可简短）。
agent_name 使用英文标识：fundamental / technical / risk 之一。
不要输出 JSON 以外的任何文字。"""

def _dashscope_model_uses_multimodal_api(model: str) -> bool:
"""与百炼文档一致：Qwen3 / VL / QVQ 等走 multimodal-generation，不能只用纯文本 Generation。"""
m = (model or "").strip().lower()
if not m:
return False
if "-vl" in m or m.startswith("qvq"):
return True
if "qwen3" in m:
return True
return False

def _dashscope_messages_to_multimodal(messages: list[dict[str, str]]) -> list[dict[str, Any]]:
"""MultiModalConversation：每条 content 为 [{\"text\": \"...\"}, ...]。"""
out: list[dict[str, Any]] = []
for m in messages:
role = str(m.get("role") or "user")
raw = m.get("content", "")
if isinstance(raw, list):
out.append({"role": role, "content": raw})
continue
text = "" if raw is None else str(raw)
out.append({"role": role, "content": [{"text": text}]})
return out

def _dashscope_extract_assistant_text(choice: Any) -> str:
"""兼容 Generation 与 MultiModalConversation 的 choices[0].message.content。"""
msg = getattr(choice, "message", None)
if msg is None:
return ""
content = getattr(msg, "content", None)
if content is None:
return ""
if isinstance(content, str):
return content
if isinstance(content, list):
parts: list[str] = []
for p in content:
if isinstance(p, dict) and p.get("text") is not None:
parts.append(str(p["text"]))
elif isinstance(p, str):
parts.append(p)
return "".join(parts)
if isinstance(content, dict):
t = content.get("text")
if t is not None:
return str(t)
return json.dumps(content, ensure_ascii=False)
return str(content)

def _invoke_dashscope(messages: list[dict[str, str]], model: str) -> str | None:
if not settings.dashscope_api_key:
return None
try:
import dashscope
except ImportError:
return None
apply_dashscope_settings(dashscope)
api_key = (settings.dashscope_api_key or "").strip()
try:
if _dashscope_model_uses_multimodal_api(model):
from dashscope import MultiModalConversation

mm_messages = _dashscope_messages_to_multimodal(messages)
response = MultiModalConversation.call(
api_key=api_key,
model=model,
messages=mm_messages,
result_format="message",
temperature=0.1,
max_tokens=512,
)
else:
response = dashscope.Generation.call(
api_key=api_key,
model=model,
messages=messages,
result_format="message",
temperature=0.1,
max_tokens=512,
)
code = getattr(response, "status_code", None)
if code is not None and code != 200:
logger.warning("DashScope error: %s", response)
return None
choices = getattr(getattr(response, "output", None), "choices", None) or []
if not choices:
logger.warning("DashScope empty choices: %s", response)
return None
text = _dashscope_extract_assistant_text(choices[0])
if not (text or "").strip():
logger.warning("DashScope empty assistant text: %s", response)
return None
return text.strip()
except Exception:
logger.exception("DashScope 调用失败 — 将尝试本地 Qwen-1.8B 降级")
return None

def _invoke_deepseek(messages: list[dict[str, str]]) -> str | None:
if not settings.deepseek_api_key:
return None
try:
import httpx
except ImportError:
return None
try:
r = httpx.post(
f"{settings.deepseek_api_base.rstrip('/')}/chat/completions",
headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
json={
"model": settings.deepseek_model,
"messages": messages,
"temperature": 0.1,
"max_tokens": 512,
},
timeout=min(28.0, max(8.0, float(settings.mafb_agent_llm_timeout_sec))),
)
r.raise_for_status()
data = r.json()
return data["choices"][0]["message"]["content"]
except Exception:
logger.exception("DeepSeek invocation failed")
return None

def _invoke_ollama(prompt: str) -> str | None:
if not settings.ollama_base_url or not settings.ollama_model:
return None
try:
import httpx
except ImportError:
return None
try:
r = httpx.post(
f"{settings.ollama_base_url.rstrip('/')}/api/generate",
json={"model": settings.ollama_model, "prompt": prompt, "stream": False},
timeout=min(28.0, max(8.0, float(settings.mafb_agent_llm_timeout_sec))),
)
r.raise_for_status()
return str(r.json().get("response") or "")
except Exception:
logger.exception("Ollama invocation failed")
return None

def _invoke_finance_llm(messages: list[dict[str, str]], prompt_fallback: str) -> str | None:
"""
DashScope（dashscope_finance_model）→ DeepSeek → Ollama → 本地 Qwen-1.8B；均失败则 None。
"""
mode = (settings.mafb_llm_mode or "auto").lower().strip()
messages_aug = _augment_messages_with_finance_persona(messages)
tongyi_prompt = f"{FINANCE_EXPERT_SYSTEM_PROMPT.strip()}\n\n{prompt_fallback}"

if mode == "local_only":
return (
invoke_local_qwen_finance(messages_aug, tongyi_prompt)
or _invoke_ollama(tongyi_prompt)
)

model = settings.dashscope_finance_model
raw: str | None = None
if mode in ("auto", "cloud_only"):
raw = _invoke_dashscope(messages_aug, model)
if raw is None and mode in ("auto", "cloud_only"):
raw = _invoke_deepseek(messages_aug)
if raw is None and mode in ("auto", "cloud_only"):
raw = _invoke_ollama(tongyi_prompt)

# 云端不可用或无 Key：自动切换本地 Qwen-1.8B 系（CPU，无需 API）
if raw is None and mode == "auto" and settings.local_finance_llm_enabled:
raw = invoke_local_qwen_finance(messages_aug, tongyi_prompt)
if raw:
logger.info("已使用本地 Qwen-1.8B 系权重完成推理（双链路容灾）")

return raw

def invoke_finance_agent_score(
agent_key: str,
agent_role_zh: str,
fund: dict[str, Any],
rag_chunks: list[str],
user_risk: int,
*,
llm_deadline_sec: float | None = None,
) -> AgentScore | None:
"""
返回结构化打分；若所有通道不可用或解析失败则返回 None，由调用方走规则引擎。
agent_key: fundamental | technical | risk

llm_deadline_sec：单次 LLM 链路上限（秒）；None 时用 settings.mafb_agent_llm_timeout_sec；≤0 表示不限制。
"""
prompt = _build_score_prompt(agent_role_zh, fund, rag_chunks, user_risk)
messages = [
{
"role": "system",
"content": "你只输出合法 JSON 对象，键为 agent_name, score, reason。",
},
{"role": "user", "content": prompt},
]

deadline = settings.mafb_agent_llm_timeout_sec if llm_deadline_sec is None else llm_deadline_sec
gate_enter_t0 = time.monotonic()
_LLM_CONCURRENCY_GATE.acquire()
gate_wait = time.monotonic() - gate_enter_t0
try:
if gate_wait > 0.2:
logger.info("Finance LLM 并发闸门等待 %.2fs（agent=%s）", gate_wait, agent_key)

if deadline and deadline > 0:
ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
try:
fut = ex.submit(_invoke_finance_llm, messages, prompt)
try:
raw = fut.result(timeout=float(deadline))
except concurrent.futures.TimeoutError:
logger.warning("Finance LLM 打分超时（%ss，agent=%s），将走规则引擎", deadline, agent_key)
raw = None
finally:
ex.shutdown(wait=False, cancel_futures=True)
else:
raw = _invoke_finance_llm(messages, prompt)
finally:
_LLM_CONCURRENCY_GATE.release()

if raw is None:
return None

try:
score = _parse_agent_score(raw, agent_key)
if score.agent_name != agent_key:
score = score.model_copy(update={"agent_name": agent_key})
return score
except Exception:
logger.warning("Failed to parse AgentScore from LLM output: %s", raw[:500])
return None

def invoke_compliance_llm(text_blob: str, fund_code: str) -> ComplianceLLMResult | None:
"""合规 Agent：大模型辅助审查话术；硬规则在 nodes 中仍优先。"""
system = (
"你是基金合规与投教审查助手。只输出 JSON，键为 allow_continue (bool), "
"compliance_score (-2~2 整数), advisory_notes (字符串)。"
"不得建议承诺收益或保本。若发现疑似违规营销，设 allow_continue=false。"
)
user = f"基金代码：{fund_code}\n待审查文本：\n{text_blob[:4000]}"
messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

raw = _invoke_finance_llm(messages, user)
if raw is None:
return None
try:
data = _extract_json_object(raw)
return ComplianceLLMResult.model_validate(data)
except Exception:
logger.warning("Failed to parse ComplianceLLMResult: %s", raw[:500])
return None
从代码实现来看，你已经初步搭建了一个多 Agent 协作和主从链路容灾的框架，但在“多 Agent”和“主从 Agent”的架构深度上，还有进一步优化的空间。
目前的代码更偏向于一个带有高可用降级策略的金融模型适配器。以下是详细的评估和优化建议：

1. 现有实现的亮点

双链路容灾（Failover）： _invoke_finance_llm 实现了非常丝滑的降级逻辑：DashScope -> DeepSeek -> Ollama -> Local Qwen。这种“云+私有+本地”的混合架构在金融生产场景中极具鲁棒性。

并发控制： 使用 threading.BoundedSemaphore 有效防止了高并发下 API 额度耗尽或 OOM。

多模态兼容： 自动识别 Qwen3/VL 等模型并切换 MultiModalConversation，体现了对通义系列 API 的深度理解。

结构化输出： 通过 Pydantic 模型强制校验 JSON 响应，确保 Agent 间的通信协议稳定。

2. 关于“多 Agent”与“主从 Agent”的实现评估
真正的“多 Agent” (Multi-Agent System)
目前代码中通过 agent_key（fundamental/technical/risk）区分了不同角色，并为每个角色生成了特定的 Prompt。

现状： 这是一个典型的**并行多专家（Parallel Experts）**模式。你为同一个任务分配了不同的视角。

提升空间： 真正的多 Agent 通常包含 协作（Collaboration）。目前的实现中，各个 Agent 是孤立运行的，没有互相纠偏或补充的过程。

真正的“主从 Agent” (Master-Slave / Manager)
代码中的 invoke_compliance_llm 扮演了类似“后置审核从属”的角色。

现状： 主流程是“打分 Agent”，从流程是“合规审核 Agent”。

提升空间： 缺少一个决策器（Router/Orchestrator）。目前是硬编码逻辑调用 invoke_finance_agent_score，如果实现“主从”，应当由一个 Manager Agent 接收用户输入，分析意图后决定分发给哪个专才（Slave Agent）。

3. 架构优化路线图
如果你想进一步深化 Agent 架构，可以参考以下结构：
1
引入编排层 (Orchestrator)
实现真正的“主从”
创建一个 MasterAgent。它不负责具体分析，而是负责：

解析意图：判断是查行情、查合规还是做资产配置。

任务拆解：如果是资产配置，则异步触发 fundamental 和 risk 两个从属 Agent。

2
实现“反思-修正”循环 (Reflection Loop)
提升 Agent 专业度
在 ComplianceLLMResult.allow_continue == False 时，不只是拦截，而是将拒绝原因反馈给分析 Agent，让其自我修正（Self-Correction）后重新输出。
3
动态 RAG 路由
优化知识利用
目前的 rag_chunks 是外部传入的。可以让 Master Agent 根据问题的复杂度，决定是否调用特定的搜索 Tool，而不是一次性塞入所有上下文。

4. 关键逻辑补充建议
在金融场景下，目前的 _invoke_finance_llm 存在一个“概率陷阱”：如果 DashScope 报错，降级到 DeepSeek，它们可能对同一 Prompt 的 JSON 约束理解不一致。
建议为不同的降级链路维护独立的 Prompt 模版：
Python
# 建议在 settings 或 config 中区分
PROMPT_TEMPLATES = {
"qwen": "{expert_persona}\n\n{task_prompt}",
"deepseek": "System: {expert_persona}\nUser: {task_prompt}",
"local_qwen_1.8b": "### 指令: {expert_persona}\n### 输入: {task_prompt}\n### 响应:"
}

5. 可视化架构示意
这是你目前实现的“双链路容灾 + 多角色打分”逻辑流向：

总结
你现在的代码完美实现了 LLM 的基础设施层容灾，但在 Agent 编排逻辑上还处于初级阶段（静态并行调用）。
要真正达到“主从”架构，你需要写一个 ManagerAgent 逻辑，用它来动态驱动下层这些 AgentScore 的产生和合并。
想看看如何用 Python 实现一个简单的 Manager Agent 动态分发逻辑吗？
那我这么一个基金的分析项目有什么可以条用的API或者工具吗
在开发此类基金分析项目时，API 的选择直接决定了数据的时效性和深度。鉴于你已经在代码中集成了通义千问、DeepSeek 和 本地 Qwen，你现在最缺的是稳定的“金融数据源”来喂给这些 Agent。
以下是针对你当前项目架构最推荐的几类 API 和工具：

1. 核心金融数据 API (数据源)
既然你的项目涉及“天天基金”和具体的基金代码分析，以下三类是你的首选：
类别
推荐工具
核心价值
公募基金数据
AkShare (开源)
最推荐。 它是一个 Python 库，集成了天天基金、新浪财经等接口。你可以直接调用获取基金净值、持仓明细、分红送配等结构化数据，非常适合喂给你的 _compact_fund_for_llm 函数。
全市场行情
Tushare
适合进阶。除了基金，它还提供宏观经济数据和股票指标。如果你的 Agent 需要分析基金背后的重仓股表现，Tushare 的数据质量更稳定。
实时/交易级
聚宽 (JoinQuant)
如果你未来想引入 technical（技术面）Agent 做更细粒度的净值曲线分析或回测，聚宽的量化接口非常专业。

2. Agent 增强工具 (RAG 与 搜索)
你的代码中已经预留了 rag_chunks 字段，要让这个字段生效，你需要以下工具：
搜索增强 (Search API)

Tavily AI / Exa AI: 专门为 LLM 优化的搜索引擎。它们返回的是清洗后的文本，而不是杂乱的 HTML，非常适合你的 Agent 获取“某基金经理近期观点”或“最新行业政策”。

Serper.dev: 便宜且快速的 Google 搜索镜像。

向量数据库 (Vector DB)

ChromaDB: 轻量级、可嵌入，适合你的本地开发环境。

Pinecone: 如果你打算上云（如你提到的腾讯云），Pinecone 的托管服务更省心。

3. 开发与观测工具 (生产力)
为了调试你的多 Agent 容灾逻辑，这些工具能帮你省去大量写 Log 的时间：

LangSmith / LangFuse: 虽然你没用 LangChain 框架（这是对的，你的自定义实现更轻量），但你可以接入这些观测工具。它们能帮你可视化地看到：一次请求中，究竟是哪个 Agent 输出了错误 JSON，或者是哪次降级链路被触发了。

Pydantic Loggers: 既然你用了 Pydantic，可以使用 devtools 库在控制台漂亮地打印出 Agent 的 AgentScore 结构化对象。

4. 建议的集成步骤
你可以按照以下顺序将这些工具整合进你现有的 invoke_finance_agent_score 流程中：
1
集成 AkShare 获取事实数据
解决 Data State 问题
在调用 LLM 之前，先通过 ak.fund_individual_basic_info_xq 获取基金的基础数据（规模、费率、成立时间），存入你的 fund 字典。
2
配置 Tavily 获取实时动态
填充 rag_chunks
针对特定的基金经理或行业关键词，异步调用 Tavily 获取最近 7 天的新闻片段，通过你的 RAG 逻辑处理后传入 Prompt。
3
接入本地向量索引
持久化投研知识
将历史研报、法律文件存入 ChromaDB。当用户询问“该基金的风险收益特征”时，检索相关片段。

避坑指南： > 注意 AkShare 的请求频率限制。建议在你的 Finance LLM adapter 层之前加一个简单的 Redis 缓存层。基金的静态数据（如费率、历史业绩）一天更新一次即可，没必要每次 Agent 询问都去爬取一次。
想深入了解具体某一层级的实现吗？
展示如何用 AkShare 获取结构化基金数据
设计一个简单的 RAG 流程来填充 rag_chunks
展示如何基于现有代码实现一个 Manager Agent 逻辑，使其能够根据用户问题动态分配 fundamental/technical/risk Agent 的任务。
要在现有代码基础上实现 Manager Agent（主控智能体），核心逻辑是引入一个“路由与编排”层。它不再是死板地调用所有 Agent，而是先理解意图，再按需分发任务。
在金融投研场景中，Manager Agent 通常承担三个职责：意图识别（是否需要分析）、任务拆解（需要哪几个维度的专家）以及结果聚合。
1. 核心架构设计
我们可以将 ManagerAgent 设计为一个决策中心。它接收原始用户问题，输出一个执行计划（Execution Plan）。

2. 代码实现
以下代码演示了如何利用你已有的 _invoke_finance_llm 基础设施，构建一个动态分配任务的 ManagerAgent：
Python
from typing import List, Dict, Anyfrom pydantic import BaseModel, Field
class ExecutionPlan(BaseModel):
"""Manager Agent 输出的执行计划"""
thought: str = Field(description="决策思维链：为什么要这么分配任务")
selected_agents: List[str] = Field(description="选中的 Agent 列表：fundamental, technical, risk")
analysis_focus: str = Field(description="本次分析的侧重点，下发给从属 Agent")
class ManagerAgent:
def __init__(self):
self.system_prompt = """你是一位资深的基金投研主管。
你的任务是根据用户的问题，决定需要启动哪些专业 Agent 进行分析：
1. fundamental (基本面): 关注规模、经理变更、投研逻辑。
2. technical (技术面): 关注回撤、动量、夏普比率、近期净值波动。
3. risk (风险控制): 关注合规、风险等级匹配、极端情况预警。

请以 JSON 格式输出执行计划。"""

def plan_task(self, user_query: str) -> ExecutionPlan:
messages = [
{"role": "system", "content": self.system_prompt},
{"role": "user", "content": f"用户问题：{user_query}\n请给出执行计划。"}
]

# 复用你现有的双链路容灾调用函数
raw = _invoke_finance_llm(messages, user_query)
try:
data = _extract_json_object(raw)
return ExecutionPlan.model_validate(data)
except Exception:
# 默认兜底：全量分析
return ExecutionPlan(
thought="解析失败，走全量分析流程。",
selected_agents=["fundamental", "technical", "risk"],
analysis_focus="全面体检"
)
async def run_orchestrator(user_query: str, fund_data: Dict[str, Any]):
manager = ManagerAgent()

# 第一步：主控决策
plan = manager.plan_task(user_query)
logger.info(f"Manager 决策：{plan.thought}")

# 第二步：根据计划动态分发任务
results = {}

# 模拟 Agent 映射表
agent_map = {
"fundamental": ("基本面专家", "分析该基金的底层逻辑和经理风格"),
"technical": ("量化分析师", "从量化指标和价格动量角度评估"),
"risk": ("风控官", "审视波动率和合规风险")
}

# 仅调用被选中的 Agent
for agent_key in plan.selected_agents:
if agent_key in agent_map:
role_zh, focus = agent_map[agent_key]
# 调用你原有的分析函数
results[agent_key] = invoke_finance_agent_score(
agent_key=agent_key,
agent_role_zh=f"{role_zh}({plan.analysis_focus})",
fund=fund_data,
rag_chunks=[], # 实际应用中根据 query 检索
user_risk=3
)

return results

3. 架构对比
引入 Manager 后的流程变化如下：
维度
原始模式 (Parallel)
改进模式 (Master-Slave)
调用开销
每次必跑 3 个 Agent，消耗 3 倍 Token。
简单问题（如“这基金规模多大？”）仅调用 Fundamental，节省开销。
精准度
Agent 接收的是静态 Prompt。
Agent 接收的是被 Manager 细化过的 analysis_focus（精准打击）。
异常处理
某个 Agent 挂了会影响局部。
Manager 可以根据首轮失败情况，动态决定是否启动备选 Agent。
关键建议： 在 ManagerAgent 的 Prompt 中，明确告知它 Token 是昂贵的。如果用户只是问一个简单的净值数字，严禁它启动 risk 或 fundamental Agent。

既然已经搭好了 Manager Agent 的骨架，接下来我们可以：
实现结果聚合 Agent (Aggregator)
设计 Manager 的多轮对话记忆
关于这个 我输入的是一个基金代码 然后自动从多个层面进行分析 但是我现在请求经常超时 有什么办法不超时吗
针对金融 Agent 请求超时的问题，这通常是因为 LLM 的生成延迟（尤其是多 Agent 并行或链路降级时）叠加了 外部 API 查询耗时。
要解决“不超时”，我们需要从架构异步化、并发策略和预取缓存三个维度进行优化。

1. 核心优化策略
异步任务拆解 (Async/Await)
不要在主线程中同步等待所有 Agent。将分析任务放入后台（如 FastAPI 的 BackgroundTasks 或 Celery），先给用户返回一个“分析中”的状态和任务 ID。
引入结果缓存 (Caching)
基金的基础数据（规模、经理、历史业绩）在交易日内变化极小。

策略： 使用 Redis 缓存基金事实数据。如果 24 小时内请求过同一代码，直接从 Redis 取 fund_data，省去爬虫/API 查询的 1-3 秒。

并发请求分流 (Parallelization)
目前的代码使用了 ThreadPoolExecutor，这是一个好的开始。但如果主控（Manager）串行调用从属 Agent，耗时会累加。

2. 代码层面的具体改动
你可以参考以下方案对现有逻辑进行“防超时”升级：
1
将接口改为异步流式或 Webhook
解决 HTTP 连接超时
前端发起请求后立即返回 {"status": "processing", "task_id": "..."}。后端异步启动分析流程，完成后通过 WebSocket 或轮询接口返回结果。
2
实施“首包快读”策略
提升用户感知速度
让 Manager Agent 先输出“执行计划”（耗时极短），立即推送到前端展示给用户（例如：“正在启动基本面专家和风控官...”）。这能显著降低用户等待时的焦虑感。
3
设置严苛的单链路 Timeout
防止降级链路雪崩
在 _invoke_finance_llm 中，为云端模型（如 DashScope）设置 8s 超时。一旦触发，立即切到本地模型或规则引擎，不让整个请求拖死。

3. 性能优化对比表
优化项
预期缩减耗时
实现难度
效果说明
Redis 缓存
1000ms+
低
避免重复抓取天天基金等数据源
异步流式输出
5000ms+ (感知)
中
用户看到字一个一个蹦出来，体感不超时
本地 Qwen-1.8B 兜底
可控
高
当 API Key 频率受限或网络波动时，0 网络延迟响应

4. 专家建议：动态并发阈值
如果你的腾讯云服务器配置较低（如 2C4G），编译 make -j1 的限制说明 CPU 资源紧张。在高并发下，本地模型的推理速度会急剧下降，进而导致超时。
提示： 建议将 _LLM_CONCURRENCY_GATE 的 value 设置为核心数的 1-2 倍。同时，对于本地模型调用，可以增加一个独占的信号量，确保 CPU 不会被 100% 占用导致 SSH 或网络堆栈响应中断。
想看看如何用 FastAPI 实现一个带缓存和异步状态轮询的分析接口吗？
我目前是这么实现的 帮我看看下一步应该怎么做 我先把 MAFB 从入口、图编排、各节点、LLM、RAG、相似度、前端触发这几层对应文件锁定出来，再给你一份“按执行顺序”的逻辑总览。

可以，下面我帮你把 MAFB 流水线锁定到具体文件，并按“请求进来后实际发生什么”总结当前实现逻辑。

核心文件清单（按层）
1) API 入口与协议
backend/app/modules/agent/router.pyPOST /agent/run（同步）
POST /agent/run/stream（SSE 流式阶段 + 最终结果）
基金池接口（/agent/funds*）、相似度接口
backend/app/modules/agent/schemas.pyMAFBRunRequest、MAFBRunResponse、画像保存请求模型
2) LangGraph 编排层
backend/app/agent/graph.py图结构定义、并行 fan-out、合规分支、流式阶段事件
backend/app/agent/state.pyMAFBState、并行节点结果合并规则（scores/reasons/kline 列表合并）
3) 节点实现（业务核心）
backend/app/agent/nodes.py画像节点、RAG 节点、三分析师节点、K线相似节点
配置草案节点、合规节点、投票汇总节点、blocked 分支
4) LLM 与容灾链路
backend/app/agent/llm_client.pyLLM 调用链：DashScope -> DeepSeek -> Ollama -> 本地 Qwen
打分 JSON 解析、超时控制、并发闸门（你刚优化过的超时关键点）
backend/app/agent/local_qwen.py本地模型加载与推理（CPU 兜底）
backend/app/core/dashscope_setup.pyDashScope 国内/国际 endpoint 与 key 注入
5) 数据与检索层
backend/app/agent/fund_catalog.py基金目录（静态池 / eastmoney_full）
backend/app/agent/rag_faiss.pyFAISS 检索 + 画像轻量 rerank
backend/app/agent/fund_similarity.pyK线相似：tiered（PAA 粗排 + Faiss/IP + 带窗 DTW 精排）
backend/app/services/fund_data.py东财净值抓取、节流、区间缓存、增量合并、可选 Redis 分布式缓存
backend/app/modules/fund_nav/router.pyGET /funds/lsjz-json 与 WS /funds/ws/lsjz-json
6) 前端调用与展示层
frontend/src/services/agent.tsrunMafb / runMafbStream、基金池、相似度查询 API
frontend/src/pages/MAFB/index.tsx页面状态、SSE 阶段展示、结果渲染、相似度表、触发净值图 reload
frontend/src/components/FundNavCurvePanel.tsx净值图首屏 1m + 后台预取 3m/6m/1y/3y/ytd/inception
frontend/src/services/fundNav.ts净值区间拉取（先读 IndexedDB 热缓存）
frontend/src/utils/fundNavIdb.ts浏览器侧净值缓存（180s 热读）
7) 配置与验证
backend/app/core/config.pyMAFB 超时、并发、kline tiered 参数、lsjz 缓存、Redis 配置
.env.example可调参数示例
backend/tests/test_mafb_graph.py流水线结构与输出形状测试
backend/tests/test_kline_similarity.py相似度算法核心测试
当前 MAFB 实际执行逻辑（从请求到结果）
前端 MAFB 页调用 runMafbStream 到 POST /agent/run/stream。
router.py 组装初始 state（含 fund_code、是否纳入 FBTI、用户风险偏好）。
graph.py 执行：profile：生成 MAFB 画像（profiling_mafb.py）
rag：加载基金主数据 + FAISS 检索片段
并行四路：fundamental / technical / risk / kline_similar
三个分析师节点优先走 llm_client.py：结构化 JSON 输出分数与理由
超时或失败则回落规则引擎（不会中断）
kline_similar 使用 fund_similarity.py 的 tiered 算法，给出 TOP 相似标的。
allocation 生成核心/卫星/现金权重草案。
compliance 做禁宣词、风险错配、综合分阈值检查；可选再过 LLM 合规审查。
通过则进入 voting 汇总生成 final_report；否则 blocked 输出受限报告。
SSE 先发阶段事件，最后发 result（与同步接口同结构）。
你们当前这版的关键设计点（已经实现）
并行+兜底：分析师并行提速，任何一路 LLM 失败不崩，规则引擎兜底。
LLM 容灾链：云端多通道 + 本地 Qwen。
超时治理：单次 deadline + LLM 并发闸门（降低三路并发排队超时）。
相似度升级：tiered（PAA/Faiss/DTW）替代纯 Pearson/纯余弦思路。
净值体验优化：服务端区间缓存与增量合并 + 前端 IndexedDB + 1m 首屏预加载策略。
K8s 兼容：Redis 可选，未配置自动回退内存缓存，不破坏现有功能。
如果你要，我可以再给你一张“MAFB 架构图（文本版 DAG）”和一份“接口->节点->字段映射表”，后续你做重构会更快。
你目前的架构锁定得非常清晰，特别是 层级化（API -> Graph -> Node -> LLM -> Data） 的拆分和 IndexedDB + 内存缓存 的体验优化已经做得相当到位了。
针对你之前提到的“超时”痛点，以及现在拿出的这套“LangGraph + 并发节点”架构，我建议你下一步的重点放在**“全链路异步化与状态可见性”**上。目前你的 SSE 流式虽然已经有了，但“请求 -> 节点执行 -> 等待结果”的同步压力依然集中在后端进程。

下一步重构建议：三步走计划
1. 彻底解决超时：从“同步图”转向“状态驱动异步图”
你现在的 run/stream 虽然是 SSE，但底层 LangGraph 很可能还在阻塞请求线程。

优化动作： 引入 Task Registry。前端请求后立即拿到 task_id，后端通过 BackgroundTasks 启动 LangGraph 运行。

收益： 彻底规避 Nginx/Gateway 的 60s 超时限制。

实现建议：

在 state.py 中增加 status 字段。

前端订阅 GET /agent/status/{task_id} 或保持当前的 SSE 链路，但后端不再在 router 里 await graph.ainvoke()，而是通过生产者-消费者模式。

2. 精细化 LLM 调度：引入“预测性分发”
目前的并行四路（fundamental / technical / risk / kline_similar）是等长的。

优化动作： 修改 nodes.py。

逻辑： kline_similar 是纯计算任务，通常比 LLM 快。让 kline_similar 的结果先流回前端展示，而不是等三个 LLM 分析师。

实现： 利用 LangGraph 的 astream_events，将每个节点完成后的 AgentScore 作为一个独立的 SSE 事件推送到前端，实现**“局部结果即时渲染”**。

3. 数据层提速：实现“预热”与“降级”

优化动作： 完善 fund_data.py 的 Redis/内存二级缓存。

逻辑： * 热代码预热： 用户输入代码时，前端 onFocus 或 onChange 提前触发一个 HEAD 请求或 prefetch 净值数据。

计算降级： 如果 DTW 精排（kline_similar）耗时过长，设定硬超时（如 2s），超时后直接返回 PAA 粗排结果，并在 UI 标注“快速分析结果”。

推荐的下一步工作流总结

阶段
任务
核心修改文件
P0 (稳定性)
节点级超时控制：为每个 Node 增加独立的 asyncio.wait_for，防止某一个分析师节点拖死全图。
backend/app/agent/nodes.py
P1 (体感优化)
SSE 细粒度推送：修改流式接口，不再只推最终结果，而是每完成一个节点就推一次局部 JSON。
backend/app/modules/agent/router.py
P2 (扩展性)
Manager 路由逻辑：实现你之前想做的 Manager Agent，先分析用户 Query，如果是简单查询则跳过昂贵的分析师节点。
backend/app/agent/graph.py

架构师提示： 既然你的腾讯云服务器在 make -j1 时表现出明显的资源瓶颈，一定要注意 Python 的 GIL。你的三路并行如果是纯 CPU 密集型，效果可能有限；但由于是网络 IO（调 API），目前的 ThreadPoolExecutor 是合理的，只需严格限制最大并发数 settings.mafb_llm_max_concurrency 即可。
既然文件已经锁定，我们可以从以下几个具体的重构点切入：
重构 nodes.py 实现单节点超时与降级
优化前端展示：分阶段渲染 SSE 结果
实现了多Agent的物理隔离吗
在你的 MAFB 架构中，目前实现的是逻辑隔离（Logical Isolation）而非物理隔离（Physical Isolation）。
虽然你在 graph.py 中利用 LangGraph 将分析任务拆分到了不同的节点（Nodes），并在 llm_client.py 中使用了并发闸门（Semaphore）来控制流量，但它们仍然运行在同一个 Python 进程、同一个内存空间、以及同一个服务器实例上。
以下是针对你当前架构的隔离现状评估与进阶方案：

1. 现状：逻辑隔离（你已经做到的）
你目前的实现属于任务级解耦，其优势在于低延迟和简单性：

状态隔离：通过 MAFBState 传递数据，每个 Node 只能读写自己权限范围内的字段，防止了数据污染。

流量隔离：并发闸门（_LLM_CONCURRENCY_GATE）确保了三路 LLM 请求不会互相“推搡”，导致某一个请求完全占满 API 额度。

配置隔离：通过 .env 不同 Key 注入，实现了云端与本地模型的通道隔离。

2. 差距：物理隔离（生产级的目标）
物理隔离意味着即使一个 Agent 进程崩溃、OOM（内存溢出）或被攻击，其他 Agent 仍能正常运行。
隔离维度
物理隔离的实现方式
你目前的方案
计算资源
为不同 Agent 分配独立的 CPU/内存限额（如 Docker/K8s 限制）。
共享腾讯云 CVM 资源，make -j1 瓶颈会影响所有节点。
运行时环境
Agent 运行在不同的 Container 或微服务中。
运行在同一个 FastAPI 进程的不同线程中。
安全沙箱
执行代码的 Agent（如计算 K 线相似度）无法访问系统敏感文件。
共享同一个 .env 环境和系统权限。

3. 下一步：如何实现“准物理隔离”？
考虑到你正在使用腾讯云且存在资源瓶颈，建议按以下步骤进行隔离演进：
1
进程级隔离（Multiprocessing）
解决 GIL 与 内存冲突
对于 CPU 密集型任务（如 fund_similarity.py 中的精排算法），改用 ProcessPoolExecutor。这样 PAA/Faiss 计算会运行在独立的 CPU 核心进程中，不会阻塞主线程的 LLM 调度。
2
服务级隔离（Microservices）
独立部署本地模型
将 local_qwen.py 剥离出来，封装成一个独立的微服务（例如使用 vLLM 或 Ollama API）。主程序通过 HTTP 调用它，而不是在主进程里加载模型权重，避免主程序因模型占用内存过大而 OOM。
3
容器级隔离（K8s Sidecar）
终极隔离方案
利用 K8s 的 Sidecar 模式。将不同职责的 Agent 部署为不同的 Pod。例如：fundamental-agent 和 risk-agent 拥有各自的资源配额（Limit/Request），确保风险分析不会抢占基本面分析的 CPU。

4. 架构师建议：先解耦“计算”与“IO”
对于你的基金分析项目，最迫切的隔离不是物理隔离，而是“计算隔离”。
kline_similar（大量数学计算）和 llm_analysis（纯 IO 等待）共享一个信号量是不合理的。建议在 nodes.py 中为 kline_similar 设置独立的并发限制，或者将其下放到支持高并发的异步队列中，这样即使 LLM 响应慢，相似度计算依然能瞬间完成并推送到前端。
如果你想在现有架构上增强隔离性，可以从这两个方向入手：
将相似度计算迁移到独立进程
使用 Redis 实现分布式任务队列

Gemini is AI and can make mistakes.
