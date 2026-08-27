from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.database import get_session
from app.models.admin import Admin, Broadcast
from app.workers.tasks import send_broadcast

router = APIRouter(prefix="/admin/broadcasts", tags=["broadcast-admin"])


class BroadcastCreateRequest(BaseModel):
    target_filter: dict = Field(default_factory=lambda: {"all": True})
    content: str = Field(min_length=1)
    content_type: str = "text"


@router.post("")
async def create_broadcast(
    payload: BroadcastCreateRequest,
    session: AsyncSession = Depends(get_session),
    admin: Admin = Depends(require_permission("broadcast.send")),
):
    """
    ينشئ سجل البث ويُطلق Celery task منفصلة فوراً (القسم 3.3-مماثل بالوثيقة):
    لا يجوز إرسال آلاف الرسائل داخل نفس طلب HTTP، لذا يعمل send_broadcast
    بشكل غير متزامن في الخلفية ويُحدِّث sent_count/failed_count عند الانتهاء.
    """
    broadcast = Broadcast(
        created_by=admin.id,
        target_filter=payload.target_filter,
        content_type=payload.content_type,
        content=payload.content,
        status="draft",
    )
    session.add(broadcast)
    await session.commit()
    await session.refresh(broadcast)

    send_broadcast.delay(broadcast.id)

    return {"broadcast_id": broadcast.id, "status": "queued"}


@router.get("/{broadcast_id}")
async def get_broadcast_status(
    broadcast_id: int,
    session: AsyncSession = Depends(get_session),
    admin: Admin = Depends(require_permission("broadcast.send")),
):
    broadcast = await session.get(Broadcast, broadcast_id)
    return {
        "id": broadcast.id,
        "status": broadcast.status,
        "sent_count": broadcast.sent_count,
        "failed_count": broadcast.failed_count,
    }
