from fastapi import APIRouter, Depends, File, UploadFile

from app.core.responses import success_response
from app.core.security import get_current_user
from app.services.fund_code_ocr import recognize_fund_from_image

router = APIRouter(prefix="/ocr", tags=["ocr"])


@router.post("/fund-code")
async def ocr_fund_code(file: UploadFile = File(...), _user=Depends(get_current_user)):
    """上传截图：优先识别 6 位代码；若无代码则按图中中文名称在全市场目录中反查代码。"""
    content = await file.read()
    data = recognize_fund_from_image(content)
    return success_response(data=data, message="OCR 处理完成")
