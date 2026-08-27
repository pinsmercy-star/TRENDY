from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import LoginRequest, TokenResponse
from app.core.security import create_access_token, verify_password
from app.database import get_session
from app.models.admin import Admin

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_session)):
    stmt = select(Admin).where(Admin.telegram_id == payload.telegram_id)
    admin = (await session.execute(stmt)).scalar_one_or_none()

    if admin is None or not admin.is_active or admin.password_hash is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "بيانات الدخول غير صحيحة")

    if not verify_password(payload.password, admin.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "بيانات الدخول غير صحيحة")

    token = create_access_token(admin.id)
    return TokenResponse(access_token=token)
