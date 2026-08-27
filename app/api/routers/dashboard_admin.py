from datetime import datetime, time

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.database import get_session
from app.models.admin import Admin, Ticket
from app.models.order import Order
from app.models.user import User
from app.models.wallet import TopupRequest

router = APIRouter(prefix="/admin/dashboard", tags=["dashboard-admin"])


@router.get("")
async def get_dashboard(
    session: AsyncSession = Depends(get_session),
    admin: Admin = Depends(require_permission("dashboard.view")),
):
    today_start = datetime.combine(datetime.utcnow().date(), time.min)

    total_users = (await session.execute(select(func.count()).select_from(User))).scalar_one()

    orders_today = (
        await session.execute(
            select(func.count()).select_from(Order).where(Order.created_at >= today_start)
        )
    ).scalar_one()

    sales_today = (
        await session.execute(
            select(func.coalesce(func.sum(Order.total_sell_amount), 0)).where(
                Order.created_at >= today_start
            )
        )
    ).scalar_one()

    profit_today = (
        await session.execute(
            select(func.coalesce(func.sum(Order.profit_amount), 0)).where(
                Order.completed_at >= today_start
            )
        )
    ).scalar_one()

    total_sales = (
        await session.execute(select(func.coalesce(func.sum(Order.total_sell_amount), 0)))
    ).scalar_one()

    total_profit = (
        await session.execute(select(func.coalesce(func.sum(Order.profit_amount), 0)))
    ).scalar_one()

    pending_orders = (
        await session.execute(
            select(func.count())
            .select_from(Order)
            .where(Order.status.in_(["processing", "sent_to_provider", "in_progress"]))
        )
    ).scalar_one()

    failed_orders = (
        await session.execute(
            select(func.count()).select_from(Order).where(Order.status.in_(["failed", "needs_review"]))
        )
    ).scalar_one()

    pending_topups = (
        await session.execute(
            select(func.count()).select_from(TopupRequest).where(TopupRequest.status == "pending")
        )
    ).scalar_one()

    open_tickets = (
        await session.execute(
            select(func.count()).select_from(Ticket).where(Ticket.status == "open")
        )
    ).scalar_one()

    return {
        "total_users": total_users,
        "orders_today": orders_today,
        "sales_today": str(sales_today),
        "profit_today": str(profit_today),
        "total_sales": str(total_sales),
        "total_profit": str(total_profit),
        "pending_orders": pending_orders,
        "failed_orders_needing_review": failed_orders,
        "pending_topups": pending_topups,
        "open_tickets": open_tickets,
    }


@router.get("/top-services")
async def top_services(
    limit: int = 10,
    session: AsyncSession = Depends(get_session),
    admin: Admin = Depends(require_permission("dashboard.view")),
):
    """أكثر الخدمات مبيعاً — البند 37 من الطلب الأصلي."""
    from app.models.service import Service

    stmt = (
        select(
            Service.name,
            func.count(Order.id).label("orders_count"),
            func.coalesce(func.sum(Order.total_sell_amount), 0).label("total_sales"),
        )
        .join(Order, Order.service_id == Service.id)
        .group_by(Service.id, Service.name)
        .order_by(func.count(Order.id).desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        {"service_name": r.name, "orders_count": r.orders_count, "total_sales": str(r.total_sales)}
        for r in rows
    ]
