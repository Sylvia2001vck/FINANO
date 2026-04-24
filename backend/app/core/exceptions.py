from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


logger = logging.getLogger(__name__)


ERROR_CODES = {
    10001: "用户不存在",
    10002: "密码错误",
    10003: "Token无效",
    20001: "OCR识别失败",
    20002: "交易数据格式错误",
    30001: "AI分析失败",
    40001: "第三方API调用失败",
}


class APIException(Exception):
    def __init__(self, code: int, message: str | None = None, status_code: int = 400):
        self.code = code
        self.message = message or ERROR_CODES.get(code, "未知错误")
        self.status_code = status_code
        super().__init__(self.message)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIException)
    async def handle_api_exception(_: Request, exc: APIException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "data": {},
                "message": exc.message,
                "code": exc.code,
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exc: Exception):
        # 勿吞掉 HTTP 层异常（404/422 等），否则会误变成 500 或丢失 /docs 等默认行为
        if isinstance(exc, StarletteHTTPException):
            return await http_exception_handler(request, exc)
        if isinstance(exc, RequestValidationError):
            return await request_validation_exception_handler(request, exc)
        logger.exception("Unhandled server error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "data": {},
                "message": "服务器内部错误",
                "code": 50000,
            },
        )
