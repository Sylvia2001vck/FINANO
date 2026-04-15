from fastapi import APIRouter, Depends, File, UploadFile

from app.core.responses import success_response
from app.core.security import get_current_user
from app.services.fund_code_ocr import recognize_fund_codes_from_image

router = APIRouter(prefix="/ocr", tags=["ocr"])


@router.post("/fund-code")
async def ocr_fund_code(file: UploadFile = File(...), _user=Depends(get_current_user)):
    """上传截图，识别其中的 6 位基金 / ETF 代码（纯代码，不解析交割单）。"""
    content = await file.read()
    codes, hint = recognize_fund_codes_from_image(content)
    primary = codes[0] if codes else None
    return success_response(
        data={"codes": codes, "primary_code": primary, "hint": hint},
        message="OCR 处理完成",
    )
