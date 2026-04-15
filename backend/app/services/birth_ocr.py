"""Extract birth date string from ID / form screenshot — reuses Baidu OCR when configured."""

from __future__ import annotations

import re
from datetime import date

from app.core.config import settings

try:
    from aip import AipOcr
except ImportError:
    AipOcr = None

_DATE_PATTERN = re.compile(
    r"(?P<y>\d{4})[年\-/.](?P<m>\d{1,2})[月\-/.](?P<d>\d{1,2})",
)


def _normalize(y: str, m: str, d: str) -> str | None:
    try:
        yi, mi, di = int(y), int(m), int(d)
        birth = date(yi, mi, di)
        if birth.year < 1900 or birth > date.today():
            return None
        return birth.isoformat()
    except ValueError:
        return None


def extract_birth_from_text(text: str) -> str | None:
    match = _DATE_PATTERN.search(text)
    if not match:
        return None
    return _normalize(match.group("y"), match.group("m"), match.group("d"))


def extract_birth_from_image(image_content: bytes) -> tuple[str | None, str]:
    if not image_content:
        return None, "空文件"

    if not all([settings.baidu_ocr_app_id, settings.baidu_ocr_api_key, settings.baidu_ocr_secret_key, AipOcr]):
        return date(2000, 1, 1).isoformat(), "未配置百度 OCR，返回演示生日 2000-01-01"

    client = AipOcr(
        settings.baidu_ocr_app_id,
        settings.baidu_ocr_api_key,
        settings.baidu_ocr_secret_key,
    )
    result = client.basicGeneral(image_content)
    words = result.get("words_result") or []
    if isinstance(words, list) and words and isinstance(words[0], dict):
        text = " ".join(item.get("words", "") for item in words)
    else:
        text = str(words)

    birth = extract_birth_from_text(text)
    if birth:
        return birth, "已从 OCR 文本解析出生日期"
    return None, "未能从 OCR 结果中解析日期，请手动输入"
