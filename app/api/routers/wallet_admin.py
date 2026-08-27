"""
Wallet Admin Router — يحقق طلبك: تزويد رصيد العميل، وسحبه إذا أراد المدير.

كل عملية هنا تمر عبر wallet_service.admin_adjust_balance (نظام الـ Ledger،
القسم 1.3 من الوثيقة) — لا يوجد أي تعديل مباشر على رقم رصيد. وكل عملية
تُسجَّل إلزامياً في audit_logs (اسم المدير، المستخدم، المبلغ، السبب، الوقت)
تماماً كما هو مطلوب بالبند 25 من الطلب الأصلي.

سحب الرصيد (debit) يمنع الرصيد من الوصول للسالب افتراضياً (enforce_non_negative)،
حتى لا يظهر عميل بدين. إن احتجت لاحقاً السماح برصيد سالب في حالة استثنائية
(مثلاً تصحيح خطأ إداري)، يمكن إضافة معامل allow_negative على مستوى صلاحية
super_admin فقط — لم يُفعَّل افتراضياً لأنه غير مطلوب حالياً وله مخاطر مالية.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.api.schemas import WalletAdjustRequest, WalletBalanceResponse, WalletLedgerEntryResponse
from app.core.audit_service import log_admin_action
from app.core.wallet_service import InsufficientBalanceError, admin_adjust_balance, get_balance
from app.database import get_session
from app.models.admin import Admin
from app.models.user import User
from app.models.wallet import WalletLedger
from sqlalchemy import select

router = APIRouter(prefix="/admin/users/{user_id}/wallet", tags=["wallet-admin"])


async def _get_user_or_404(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المستخدم غير موجود")
    return user


@router.get("", response_model=WalletBalanceResponse)
async def get_wallet(
    user_id: int,
    session: AsyncSession = Depends(get_session),
    admin: Admin = Depends(require_permission("wallet.view")),
):
    user = await _get_user_or_404(session, user_id)
    balance = await get_balance(session, user_id)

    stmt = (
        select(WalletLedger)
        .where(WalletLedger.user_id == user_id)
        .order_by(WalletLedger.id.desc())
        .limit(20)
    )
    entries = (await session.execute(stmt)).scalars().all()

    return WalletBalanceResponse(
        user_id=user.id,
        balance=balance,
        currency=entries[0].currency if entries else "IQD",
        recent_entries=[WalletLedgerEntryResponse.model_validate(e) for e in entries],
    )


@router.post("/credit", response_model=WalletBalanceResponse, status_code=status.HTTP_201_CREATED)
async def credit_wallet(
    user_id: int,
    payload: WalletAdjustRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: Admin = Depends(require_permission("wallet.adjust")),
):
    """تزويد رصيد العميل — يُنشئ سطر Ledger موجب ويُسجَّل في Audit Log."""
    user = await _get_user_or_404(session, user_id)
    balance_before = await get_balance(session, user_id)

    entry = await admin_adjust_balance(
        session,
        user_id=user.id,
        amount=abs(payload.amount),
        currency=payload.currency,
        admin_id=admin.id,
        reason=payload.reason,
    )

    await log_admin_action(
        session,
        admin_id=admin.id,
        action="wallet.credit",
        target_type="user",
        target_id=user.id,
        old_value={"balance": str(balance_before)},
        new_value={"balance": str(entry.balance_after), "amount": str(payload.amount), "reason": payload.reason},
        ip_address=request.client.host if request.client else None,
    )
    await session.commit()

    return WalletBalanceResponse(
        user_id=user.id, balance=entry.balance_after, currency=payload.currency, recent_entries=[]
    )


@router.post("/debit", response_model=WalletBalanceResponse, status_code=status.HTTP_201_CREATED)
async def debit_wallet(
    user_id: int,
    payload: WalletAdjustRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: Admin = Depends(require_permission("wallet.adjust")),
):
    """سحب رصيد من العميل (خصم يدوي) — يرفض إن كان الرصيد أقل من المبلغ المطلوب سحبه."""
    user = await _get_user_or_404(session, user_id)
    balance_before = await get_balance(session, user_id)

    try:
        entry = await admin_adjust_balance(
            session,
            user_id=user.id,
            amount=-abs(payload.amount),
            currency=payload.currency,
            admin_id=admin.id,
            reason=payload.reason,
        )
    except InsufficientBalanceError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"لا يمكن سحب هذا المبلغ — رصيد العميل الحالي {balance_before} فقط",
        ) from exc

    await log_admin_action(
        session,
        admin_id=admin.id,
        action="wallet.debit",
        target_type="user",
        target_id=user.id,
        old_value={"balance": str(balance_before)},
        new_value={"balance": str(entry.balance_after), "amount": str(payload.amount), "reason": payload.reason},
        ip_address=request.client.host if request.client else None,
    )
    await session.commit()

    return WalletBalanceResponse(
        user_id=user.id, balance=entry.balance_after, currency=payload.currency, recent_entries=[]
    )
