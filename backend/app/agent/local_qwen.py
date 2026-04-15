"""
本地 Qwen-1.8B 系金融推理（CPU，无需 API）。

默认权重 ID 为 `Qwen/Qwen1.8B-Chat`（阿里开源 1.8B）；可在环境变量中替换为社区
「Qwen-1.8B-Finance」等金融微调 checkpoint，实现「云端 API + 本地开源双链路容灾」。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_model = None
_tokenizer = None
_load_lock = threading.Lock()
_load_attempted_model_id: str | None = None
_load_error: str | None = None


def _messages_to_prompt(tokenizer: Any, messages: list[dict[str, str]]) -> str:
    if getattr(tokenizer, "chat_template", None):
        try:
            return tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        except Exception:
            logger.debug("apply_chat_template failed, falling back to plain concat", exc_info=True)
    lines = []
    for m in messages:
        lines.append(f"{m['role']}: {m['content']}")
    lines.append("assistant:")
    return "\n".join(lines)


def _load_model(model_id: str) -> tuple[Any, Any] | tuple[None, None]:
    global _model, _tokenizer, _load_attempted_model_id, _load_error
    with _load_lock:
        if _load_error and _load_attempted_model_id == model_id:
            return None, None
        if _model is not None and _tokenizer is not None and _load_attempted_model_id == model_id:
            return _model, _tokenizer
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError:
            _load_error = "未安装 torch / transformers，无法启用本地 Qwen（见 requirements-optional-local-llm.txt）"
            _load_attempted_model_id = model_id
            logger.info(_load_error)
            return None, None

        try:
            tok = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
            if tok.pad_token_id is None and tok.eos_token_id is not None:
                tok.pad_token = tok.eos_token
            mdl = AutoModelForCausalLM.from_pretrained(
                model_id,
                trust_remote_code=True,
                torch_dtype=torch.float32,
                device_map="cpu",
                low_cpu_mem_usage=True,
            )
            mdl.eval()
            _tokenizer = tok
            _model = mdl
            _load_attempted_model_id = model_id
            _load_error = None
            logger.info("本地金融小模型已加载: %s (CPU float32)", model_id)
            return _model, _tokenizer
        except Exception as exc:
            _load_error = str(exc)
            _load_attempted_model_id = model_id
            logger.warning("本地模型加载失败 %s: %s", model_id, exc)
            return None, None


def invoke_local_qwen_finance(messages: list[dict[str, str]], prompt_fallback: str) -> str | None:
    """
    使用本地 Qwen-1.8B 系权重生成续写文本（期望模型输出中包含可解析 JSON）。
    无模型 ID、无依赖或加载失败时返回 None。
    """
    if not settings.local_finance_llm_enabled:
        return None
    model_id = (settings.local_finance_model_id or "").strip()
    if not model_id:
        return None

    model, tokenizer = _load_model(model_id)
    if model is None or tokenizer is None:
        return None

    try:
        import torch
    except ImportError:
        return None

    prompt = _messages_to_prompt(tokenizer, messages) if messages else prompt_fallback
    inputs = tokenizer(prompt, return_tensors="pt")
    if "token_type_ids" in inputs:
        del inputs["token_type_ids"]

    max_new = max(64, min(settings.local_finance_max_new_tokens, 1024))
    pad_id = tokenizer.pad_token_id or tokenizer.eos_token_id

    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens=max_new,
            do_sample=False,
            temperature=None,
            top_p=None,
            pad_token_id=pad_id,
        )

    prompt_len = inputs["input_ids"].shape[1]
    gen_ids = out[0, prompt_len:]
    text = tokenizer.decode(gen_ids, skip_special_tokens=True).strip()
    return text or None


def reset_local_model_cache() -> None:
    """测试或热切换模型 ID 时可调用。"""
    global _model, _tokenizer, _load_attempted_model_id, _load_error
    with _load_lock:
        _model = None
        _tokenizer = None
        _load_attempted_model_id = None
        _load_error = None
