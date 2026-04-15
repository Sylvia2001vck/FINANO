"""EasyOCR：从图片中抽取 6 位基金 / ETF 代码（如 005827）。安装：pip install -r requirements-optional-easyocr.txt"""

from __future__ import annotations

import io
import re
import tempfile
from pathlib import Path

# 中英文场景：EasyOCR 中文简体的语言码为 ch_sim（无独立 'zh' 代号）
_OCR_LANGS = ["en", "ch_sim"]

# 优先匹配「非数字边界内的 6 位数字」，减少误伤长串；再兜底任意 6 位连续数字
_RE_ISOLATED = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_RE_FALLBACK = re.compile(r"\d{6}")

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


def recognize_fund_codes_from_image(image_bytes: bytes) -> tuple[list[str], str]:
    """
    使用 EasyOCR + numpy 数组推理；若环境异常则尝试临时文件路径（与 readtext(img_path, detail=0) 行为一致）。
    """
    reader = _get_reader()
    if reader is None:
        return [], "未安装 EasyOCR：请执行 pip install -r requirements-optional-easyocr.txt（含 Pillow）"

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
        # detail=0 → 仅返回字符串列表，与官方推荐用法一致
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

    codes = extract_codes_from_texts(texts)
    if not codes:
        return [], "未识别到 6 位基金代码，请上传含代码的清晰截图（如 005827、510300）"
    return codes, f"共识别 {len(codes)} 个候选代码"
