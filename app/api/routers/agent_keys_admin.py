import secrets

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.crypto import encrypt_secret
from app.database import get_session
from app.models.admin import Admin
from app.models.provider import AgentApiKey

router = APIRouter(prefix="/admin/users/{user_id}/agent-keys", tags=["agent-keys-admin"])


@router.post("")
async def create_agent_key(
    user_id: int,
    session: AsyncSession = Depends(get_session),
    admin: Admin = Depends(require_permission("agents.manage")),
):
    """
    يولّد مفتاح API عشوائياً للوكيل ويخزّنه مشفّراً. المفتاح الصريح يُعاد
    مرة واحدة فقط بهذه الاستجابة — لا يمكن استرجاعه لاحقاً (نفس مبدأ كلمات
    مرور API لدى أي مزود احترافي)، فقط توليد مفتاح جديد إن ضاع.
    """
    plain_key = f"trd_{secrets.token_urlsafe(32)}"

    agent_key = AgentApiKey(user_id=user_id, api_key_encrypted=encrypt_secret(plain_key), is_active=True)
    session.add(agent_key)
    await session.commit()

    return {"api_key": plain_key, "note": "احفظ هذا المفتاح الآن — لن يظهر مرة أخرى"}


@router.delete("/{key_id}")
async def revoke_agent_key(
    user_id: int,
    key_id: int,
    session: AsyncSession = Depends(get_session),
    admin: Admin = Depends(require_permission("agents.manage")),
):
    key = await session.get(AgentApiKey, key_id)
    if key is not None:
        key.is_active = False
        await session.commit()
    return {"status": "revoked"}
