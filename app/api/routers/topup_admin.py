from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.api.schemas import TopupRejectRequest
from app.core.audit_service import log_admin_action
from app.core.telegram_notify import send_telegram_message
from app.core.wallet_service import add_ledger_entry
from app.database import get_session
from app.models.admin import Admin
from app.models.user import User
from app.models.wallet import TopupRequest
from datetime import datetime

router = APIRouter(prefix="/admin/topups", tags=["topups-admin"])


async def _get_topup_or_404(session: AsyncSession, topup_id: int) -> TopupRequest:
    topup = await session.get(TopupRequest, topup_id)
    if topup is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "طلب الشحن غير موجود")
    if topup.status != "pending":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "تمت مراجعة هذا الطلب مسبقاً")
    return topup


@router.post("/{topup_id}/approve")
async def approve_topup(
    topup_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: Admin = Depends(require_permission("wallet.adjust")),
):
    """موافقة على شحن يدوي — يُضيف الرصيد فعلياً عبر الـ Ledger (البند 10 من الطلب الأصلي)."""
    topup = await _get_topup_or_404(session, topup_id)

    entry = await add_ledger_entry(
        session,
        user_id=topup.user_id,
        amount=abs(topup.amount),
        currency=topup.currency,
        entry_type="topup",
        reference_type="payment",
        reference_id=topup.id,
        description=f"شحن رصيد موافق عليه من {admin.full_name}",
        created_by=admin.id,
    )

    topup.status = "approved"
    topup.reviewed_by = admin.id
    topup.reviewed_at = datetime.utcnow()

    await log_admin_action(
        session,
        admin_id=admin.id,
        action="topup.approve",
        target_type="topup_request",
        target_id=topup.id,
        new_value={"amount": str(topup.amount), "new_balance": str(entry.balance_after)},
        ip_address=request.client.host if request.client else None,
    )
    await session.commit()

    user = await session.get(User, topup.user_id)
    if user is not None:
        await send_telegram_message(
            user.telegram_id,
            f"✅ تم شحن رصيدك بمبلغ {topup.amount} {topup.currency} بنجاح.\nرصيدك الحالي: {entry.balance_after}",
        )

    return {"status": "approved", "new_balance": str(entry.balance_after)}


@router.post("/{topup_id}/reject")
async def reject_topup(
    topup_id: int,
    payload: TopupRejectRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: Admin = Depends(require_permission("wallet.adjust")),
):
    topup = await _get_topup_or_404(session, topup_id)

    topup.status = "rejected"
    topup.reviewed_by = admin.id
    topup.reviewed_at = datetime.utcnow()
    topup.rejection_reason = payload.reason

    await log_admin_action(
        session,
        admin_id=admin.id,
        action="topup.reject",
        target_type="topup_request",
        target_id=topup.id,
        new_value={"reason": payload.reason},
        ip_address=request.client.host if request.client else None,
    )
    await session.commit()

    user = await session.get(User, topup.user_id)
    if user is not None:
        await send_telegram_message(
            user.telegram_id,
            f"❌ تم رفض طلب شحنك بمبلغ {topup.amount} {topup.currency}.\nالسبب: {payload.reason}",
        )

    return {"status": "rejected"}
