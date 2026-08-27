from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.generic_adapter import GenericHttpAdapter
from app.database import get_session
from app.models.admin import Admin
from app.models.provider import Provider, ProviderService

router = APIRouter(prefix="/admin/providers", tags=["providers-admin"])


class ProviderCreateRequest(BaseModel):
    name: str
    api_url: str
    api_key: str  # نص عادي — يُشفَّر داخلياً قبل التخزين، لا يُخزَّن أبداً كما هو
    api_style: str = "standard_smm_api"
    endpoint_map: dict = Field(default_factory=dict)
    low_balance_threshold: float = 10


class ImportServiceRequest(BaseModel):
    service_id: int  # الخدمة الداخلية بـ TRENDY المراد ربطها
    provider_service_id: str
    cost_price: float
    priority: int = 1


@router.post("")
async def create_provider(
    payload: ProviderCreateRequest,
    session: AsyncSession = Depends(get_session),
    admin: Admin = Depends(require_permission("providers.manage")),
):
    """إضافة مزود جديد — القسم 3.2.1 بالوثيقة: بدون أي تعديل كود، فقط تعبئة هذا النموذج."""
    provider = Provider(
        name=payload.name,
        api_url=payload.api_url,
        api_key_encrypted=encrypt_secret(payload.api_key),
        api_style=payload.api_style,
        endpoint_map=payload.endpoint_map,
        low_balance_threshold=payload.low_balance_threshold,
        status="active",
    )
    session.add(provider)
    await session.commit()
    await session.refresh(provider)
    return {"id": provider.id, "name": provider.name}


@router.post("/{provider_id}/test-connection")
async def test_connection(
    provider_id: int,
    session: AsyncSession = Depends(get_session),
    admin: Admin = Depends(require_permission("providers.manage")),
):
    """اختبار الاتصال — البند 28 من الطلب الأصلي."""
    provider = await session.get(Provider, provider_id)
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المزود غير موجود")

    adapter = GenericHttpAdapter(provider, decrypt_secret(provider.api_key_encrypted))
    try:
        balance = await adapter.get_balance()
        return {"connected": True, "balance": str(balance)}
    except Exception as exc:  # noqa: BLE001
        return {"connected": False, "error": str(exc)}
    finally:
        await adapter.aclose()


@router.post("/{provider_id}/sync-preview")
async def sync_services_preview(
    provider_id: int,
    session: AsyncSession = Depends(get_session),
    admin: Admin = Depends(require_permission("providers.manage")),
):
    """
    زر "مزامنة الخدمات" — البند 6 من الطلب الأصلي. يجلب فقط قائمة الخدمات
    المتاحة لدى المزود للمعاينة، دون إضافتها تلقائياً — الإدارة تختار
    الخدمات المطلوبة يدوياً بعدها عبر /import-service (حسب طلبك الأصلي:
    "أستطيع اختيار الخدمات التي أريد إضافتها").
    """
    provider = await session.get(Provider, provider_id)
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المزود غير موجود")

    adapter = GenericHttpAdapter(provider, decrypt_secret(provider.api_key_encrypted))
    try:
        services = await adapter.sync_services()
        provider.last_sync_at = __import__("datetime").datetime.utcnow()
        await session.commit()
        return [
            {
                "provider_service_id": s.provider_service_id,
                "name": s.name,
                "category": s.category,
                "rate_per_1000": str(s.rate_per_1000),
                "min_order": s.min_order,
                "max_order": s.max_order,
            }
            for s in services
        ]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"فشل الاتصال بالمزود: {exc}") from exc
    finally:
        await adapter.aclose()


@router.post("/{provider_id}/import-service")
async def import_service(
    provider_id: int,
    payload: ImportServiceRequest,
    session: AsyncSession = Depends(get_session),
    admin: Admin = Depends(require_permission("providers.manage")),
):
    """يربط خدمة داخلية موجودة مسبقاً بخدمة المزود المختارة من المعاينة أعلاه."""
    provider_service = ProviderService(
        service_id=payload.service_id,
        provider_id=provider_id,
        provider_service_id=payload.provider_service_id,
        cost_price=payload.cost_price,
        priority=payload.priority,
        is_active=True,
    )
    session.add(provider_service)
    await session.commit()
    await session.refresh(provider_service)
    return {"id": provider_service.id, "status": "linked"}
