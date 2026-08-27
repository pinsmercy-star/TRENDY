from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import require_permission
from app.core.backup_service import create_backup, list_backups, restore_backup
from app.models.admin import Admin

router = APIRouter(prefix="/admin/backups", tags=["backups-admin"])


@router.get("")
async def get_backups(admin: Admin = Depends(require_permission("backups.manage"))):
    return list_backups()


@router.post("/run")
async def run_manual_backup(admin: Admin = Depends(require_permission("backups.manage"))):
    try:
        path = create_backup()
        return {"status": "success", "filename": path.name}
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc


@router.post("/{filename}/restore")
async def run_restore(filename: str, admin: Admin = Depends(require_permission("backups.manage"))):
    """⚠️ عملية خطيرة — تستبدل قاعدة البيانات الحالية بالكامل. محمية بصلاحية منفصلة صراحةً."""
    try:
        restore_backup(filename)
        return {"status": "restored", "filename": filename}
    except (RuntimeError, FileNotFoundError) as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
