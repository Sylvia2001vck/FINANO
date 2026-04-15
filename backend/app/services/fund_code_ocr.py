"""EasyOCR：从图片中抽取 6 位基金代码；若无代码则尝试从中文名称在全市场目录中反查代码。"""

from __future__ import annotations

import io
import re
import tempfile
from pathlib import Path
from typing import Any

# 中英文场景：EasyOCR 中文简体的语言码为 ch_sim（无独立 'zh' 代号）
_OCR_LANGS = ["en", "ch_sim"]

# 优先匹配「非数字边界内的 6 位数字」，减少误伤长串；再兜底任意 6 位连续数字
_RE_ISOLATED = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_RE_FALLBACK = re.compile(r"\d{6}")
_RE_ZH_CHUNK = re.compile(r"[\u4e00-\u9fff]{2,40}")

_reader = None


def _get_reader():
    global _reader
    if _reader is not None:
        return _reader
    try:
        import easyocr  # noqa: PLC0415
    except ImportError:
        return None
    _reader = easyocr.Reader(_OCR_LANGS, gpu=False, verbose=False)
    return _reader


def extract_codes_from_texts(texts: list[str]) -> list[str]:
    """从 OCR 文本行中提取基金代码（去重保序）。"""
    found: list[str] = []
    for raw in texts:
        line = raw.replace(" ", "").replace("O", "0").replace("o", "0")
        for m in _RE_ISOLATED.findall(line):
            if m not in found:
                found.append(m)
        if not _RE_ISOLATED.search(line):
            for m in _RE_FALLBACK.findall(line):
                if m not in found:
                    found.append(m)
    return found[:15]


def _collect_name_candidates(lines: list[str]) -> list[str]:
    """从 OCR 行中提取可能的中文基金名片段（长优先）。"""
    out: list[str] = []
    for line in lines:
        s = line.strip()
        if not s or re.fullmatch(r"\d{6}", s):
            continue
        for m in _RE_ZH_CHUNK.findall(s):
            if m not in out and len(m) >= 2:
                out.append(m)
        if _RE_ZH_CHUNK.search(s) and s not in out and len(s) >= 3:
            out.append(s)
    out.sort(key=len, reverse=True)
    return out[:15]


def _read_easyocr_lines(reader: Any, image_bytes: bytes) -> tuple[list[str], str]:
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return [], "需要 Pillow：pip install Pillow"

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        arr = np.array(img)
    except Exception as exc:  # noqa: BLE001
        return [], f"无法解析图片：{exc}"

    texts: list[str] = []
    try:
        line_texts = reader.readtext(arr, detail=0)
        if isinstance(line_texts, str):
            texts = [line_texts]
        else:
            texts = [str(t) for t in line_texts if t]
    except Exception:  # noqa: BLE001
        texts = []

    if not texts:
        tmp: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(image_bytes)
                tmp = Path(f.name)
            line_texts = reader.readtext(str(tmp), detail=0)
            if isinstance(line_texts, str):
                texts = [line_texts]
            else:
                texts = [str(t) for t in line_texts if t]
        except Exception as exc:  # noqa: BLE001
            return [], f"OCR 失败：{exc}"
        finally:
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass

    return texts, ""


def recognize_fund_from_image(image_bytes: bytes) -> dict[str, Any]:
    """
    返回 codes、primary_code、matched_name（若由名称反查）、hint、ocr_lines。
    """
    reader = _get_reader()
    if reader is None:
        return {
            "codes": [],
            "primary_code": None,
            "matched_name": None,
            "hint": "未安装 EasyOCR：请执行 pip install -r requirements-optional-easyocr.txt（含 Pillow）",
            "ocr_lines": [],
        }

    texts, err = _read_easyocr_lines(reader, image_bytes)
    if err:
        return {"codes": [], "primary_code": None, "matched_name": None, "hint": err, "ocr_lines": []}

    codes = extract_codes_from_texts(texts)
    primary: str | None = codes[0] if codes else None
    matched_name: str | None = None

    if not primary:
        from app.agent.fund_catalog import resolve_fund_code_by_name_query

        for cand in _collect_name_candidates(texts):
            hit = resolve_fund_code_by_name_query(cand)
            if hit:
                primary = hit
                matched_name = cand
                break

    if primary:
        if matched_name:
            hint = f"已匹配基金代码 {primary}（按图中名称「{matched_name}」在全库检索）"
        elif len(codes) > 1:
            hint = f"识别到 {len(codes)} 个代码候选，主代码取首个：{primary}"
        else:
            hint = "已从图中识别 6 位基金代码"
    else:
        hint = "未识别到 6 位代码，且无法从图中文本可靠匹配基金名称；请换清晰截图或手动输入代码"

    return {
        "codes": codes,
        "primary_code": primary,
        "matched_name": matched_name,
        "hint": hint,
        "ocr_lines": texts[:24],
    }


def recognize_fund_codes_from_image(image_bytes: bytes) -> tuple[list[str], str]:
    """兼容旧接口：仅返回 (codes, hint)。"""
    d = recognize_fund_from_image(image_bytes)
    return d["codes"], str(d["hint"])
