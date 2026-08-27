from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.telegram_notify import send_telegram_message
from app.database import get_session
from app.models.admin import Admin, Ticket, TicketMessage
from app.models.user import User

router = APIRouter(prefix="/admin/tickets", tags=["tickets-admin"])


class TicketReplyRequest(BaseModel):
    message: str = Field(min_length=1)


@router.get("")
async def list_tickets(
    status_filter: str | None = None,
    session: AsyncSession = Depends(get_session),
    admin: Admin = Depends(require_permission("tickets.view")),
):
    stmt = select(Ticket).order_by(Ticket.created_at.desc())
    if status_filter:
        stmt = stmt.where(Ticket.status == status_filter)
    tickets = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": t.id,
            "ticket_code": t.ticket_code,
            "category": t.category,
            "status": t.status,
            "user_id": t.user_id,
            "created_at": t.created_at.isoformat(),
        }
        for t in tickets
    ]


@router.get("/{ticket_id}")
async def get_ticket(
    ticket_id: int,
    session: AsyncSession = Depends(get_session),
    admin: Admin = Depends(require_permission("tickets.view")),
):
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "التذكرة غير موجودة")

    stmt = select(TicketMessage).where(TicketMessage.ticket_id == ticket_id).order_by(TicketMessage.created_at)
    messages = (await session.execute(stmt)).scalars().all()

    return {
        "id": ticket.id,
        "ticket_code": ticket.ticket_code,
        "status": ticket.status,
        "category": ticket.category,
        "messages": [
            {"sender_type": m.sender_type, "message": m.message, "created_at": m.created_at.isoformat()}
            for m in messages
        ],
    }


@router.post("/{ticket_id}/reply")
async def reply_ticket(
    ticket_id: int,
    payload: TicketReplyRequest,
    session: AsyncSession = Depends(get_session),
    admin: Admin = Depends(require_permission("tickets.reply")),
):
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "التذكرة غير موجودة")

    session.add(
        TicketMessage(
            ticket_id=ticket.id, sender_type="admin", sender_id=admin.id, message=payload.message
        )
    )
    ticket.status = "answered"
    ticket.assigned_to = admin.id
    await session.commit()

    user = await session.get(User, ticket.user_id)
    if user is not None:
        await send_telegram_message(
            user.telegram_id,
            f"📩 رد جديد على تذكرتك #{ticket.ticket_code}:\n\n{payload.message}",
        )

    return {"status": "replied"}


@router.post("/{ticket_id}/close")
async def close_ticket(
    ticket_id: int,
    session: AsyncSession = Depends(get_session),
    admin: Admin = Depends(require_permission("tickets.reply")),
):
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "التذكرة غير موجودة")
    ticket.status = "closed"
    await session.commit()
    return {"status": "closed"}
