"""
Agent API — البند 41 من الطلب الأصلي: "الوكيل يرسل طلب إلى API الخاص بي...
ويعود Status إلى الوكيل". هذا الراوتر منفصل تماماً عن راوترات /admin (مصادقة
مختلفة تماماً: X-API-Key بدل JWT)، ليصبح TRENDY منصة بيع خدمات فعلياً وليس
مجرد بوت — بالضبط كما هو موصوف بالبند 41.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.agent_deps import get_current_agent
from app.core.order_service import OrderValidationError, create_order
from app.core.wallet_service import get_balance
from app.database import get_session
from app.models.service import Service
from app.models.user import User
from app.workers.tasks import dispatch_order
from sqlalchemy import select
from app.models.order import Order

router = APIRouter(prefix="/agent/v1", tags=["agent-api"])


class AgentOrderRequest(BaseModel):
    service_internal_code: str
    link: str
    quantity: int = Field(gt=0)


@router.get("/balance")
async def agent_get_balance(
    agent_user: User = Depends(get_current_agent),
    session: AsyncSession = Depends(get_session),
):
    balance = await get_balance(session, agent_user.id)
    return {"balance": str(balance)}


@router.post("/orders", status_code=status.HTTP_201_CREATED)
async def agent_create_order(
    payload: AgentOrderRequest,
    agent_user: User = Depends(get_current_agent),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Service).where(Service.internal_code == payload.service_internal_code)
    service = (await session.execute(stmt)).scalar_one_or_none()
    if service is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الخدمة غير موجودة")

    try:
        order = await create_order(
            session,
            user=agent_user,
            service=service,
            quantity=payload.quantity,
            link_or_target=payload.link,
        )
        await session.commit()
    except OrderValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    dispatch_order.delay(order.id)

    return {"order_code": order.order_code, "status": order.status, "total_amount": str(order.total_sell_amount)}


@router.get("/orders/{order_code}")
async def agent_get_order_status(
    order_code: str,
    agent_user: User = Depends(get_current_agent),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Order).where(Order.order_code == order_code, Order.user_id == agent_user.id)
    order = (await session.execute(stmt)).scalar_one_or_none()
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الطلب غير موجود")

    return {
        "order_code": order.order_code,
        "status": order.status,
        "quantity": order.quantity,
        "total_amount": str(order.total_sell_amount),
        "provider_last_status": order.provider_last_status,
    }
