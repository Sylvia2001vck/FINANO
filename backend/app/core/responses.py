from typing import Any


def success_response(data: Any = None, message: str = "操作成功") -> dict:
    return {
        "success": True,
        "data": data if data is not None else {},
        "message": message,
    }
