from datetime import date

from app.core.config import settings
from app.core.exceptions import APIException

try:
    from aip import AipOcr
except ImportError:
    AipOcr = None


def _to_float(value, default: float = 0) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _fallback_trade() -> list[dict]:
    today = date.today().isoformat()
    return [
        {
            "trade_date": today,
            "symbol": "600519",
            "name": "贵州茅台",
            "direction": "buy",
            "quantity": 100,
            "price": 1800,
            "amount": 180000,
            "fee": 15,
            "profit": 3200,
            "platform": "ocr_demo",
            "notes": "未配置百度 OCR，已回退到演示样例数据",
        }
    ]


def recognize_statement(image_content: bytes):
    if not image_content:
        raise APIException(code=20001, message="上传文件为空", status_code=400)

    if not all(
        [
            settings.baidu_ocr_app_id,
            settings.baidu_ocr_api_key,
            settings.baidu_ocr_secret_key,
            AipOcr,
        ]
    ):
        return _fallback_trade()

    client = AipOcr(
        settings.baidu_ocr_app_id,
        settings.baidu_ocr_api_key,
        settings.baidu_ocr_secret_key,
    )
    result = client.financeBill(image_content)
    words_result = result.get("words_result")
    if not words_result:
        raise APIException(code=20001, message="OCR 未识别出有效字段", status_code=400)

    items = words_result if isinstance(words_result, list) else [words_result]
    trades = []
    for item in items:
        trades.append(
            {
                "trade_date": item.get("交易日期", {}).get("word") or date.today().isoformat(),
                "symbol": item.get("证券代码", {}).get("word", "UNKNOWN"),
                "name": item.get("证券名称", {}).get("word", "未知标的"),
                "direction": "buy" if "买" in item.get("买卖方向", {}).get("word", "") else "sell",
                "quantity": _to_float(item.get("成交数量", {}).get("word", 0), 1),
                "price": _to_float(item.get("成交价格", {}).get("word", 0), 1),
                "amount": _to_float(item.get("成交金额", {}).get("word", 0), 1),
                "fee": _to_float(item.get("手续费", {}).get("word", 0), 0),
                "profit": 0,
                "platform": "ocr_baidu",
                "notes": "由百度 OCR 自动识别导入",
            }
        )

    return trades
