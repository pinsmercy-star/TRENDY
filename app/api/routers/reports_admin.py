from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.report_service import generate_csv_report, generate_excel_report, generate_pdf_report
from app.database import get_session
from app.models.admin import Admin

router = APIRouter(prefix="/admin/reports", tags=["reports-admin"])

MEDIA_TYPES = {
    "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "pdf": "application/pdf",
}
EXTENSIONS = {"excel": "xlsx", "csv": "csv", "pdf": "pdf"}
GENERATORS = {"excel": generate_excel_report, "csv": generate_csv_report, "pdf": generate_pdf_report}


@router.get("/orders")
async def export_orders_report(
    start: datetime,
    end: datetime,
    format: str = "excel",  # excel | csv | pdf
    session: AsyncSession = Depends(get_session),
    admin: Admin = Depends(require_permission("reports.export")),
):
    if format not in GENERATORS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "الصيغة يجب أن تكون excel أو csv أو pdf")

    content = await GENERATORS[format](session, start, end)
    filename = f"trendy-report-{start.date()}-{end.date()}.{EXTENSIONS[format]}"

    return Response(
        content=content,
        media_type=MEDIA_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
