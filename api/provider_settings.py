from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from application.provider_settings import ProviderSettingsService

router = APIRouter(prefix="/provider-settings", tags=["provider-settings"])
service = ProviderSettingsService()


class ProviderSettingUpsertRequest(BaseModel):
    id: int | None = None
    provider_type: str
    provider_key: str
    display_name: str = ""
    auth_mode: str = ""
    enabled: bool = True
    is_default: bool = False
    config: dict[str, str] = Field(default_factory=dict)
    auth: dict[str, str] = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


@router.get("")
def list_provider_settings(provider_type: str):
    return service.list_settings(provider_type)


@router.put("")
def save_provider_setting(body: ProviderSettingUpsertRequest):
    try:
        return service.save_setting(body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("")
def create_provider_setting(body: ProviderSettingUpsertRequest):
    try:
        return service.save_setting(body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.delete("/{setting_id}")
def delete_provider_setting(setting_id: int):
    result = service.delete_setting(setting_id)
    if not result["ok"]:
        raise HTTPException(404, "provider setting 不存在")
    return result


class TestMailboxRequest(BaseModel):
    action: str  # "generate" or "wait_code"
    provider_key: str
    config: dict[str, str] = Field(default_factory=dict)
    auth: dict[str, str] = Field(default_factory=dict)
    email: str = ""
    account_id: str = ""
    keyword: str = ""
    timeout: int = 20


@router.post("/test-mailbox")
def test_mailbox(body: TestMailboxRequest):
    from core.base_mailbox import MAILBOX_FACTORY_REGISTRY, MailboxAccount
    from infrastructure.provider_definitions_repository import ProviderDefinitionsRepository
    try:
        # 直接使用工厂创建驱动，避免通过 create_mailbox 走数据库配置和 Fallback 逻辑
        definitions_repo = ProviderDefinitionsRepository()
        definition = definitions_repo.get_by_key("mailbox", body.provider_key)
        lookup_key = definition.driver_type if definition else body.provider_key
        
        factory = MAILBOX_FACTORY_REGISTRY.get(lookup_key)
        if not factory:
            raise HTTPException(400, f"Driver factory not found for: {lookup_key}")
            
        combo = {**body.config, **body.auth}
        
        # 统一处理工厂参数（有些工厂需要 pipeline_config）
        if lookup_key in ("generic_http_mailbox", "generic_http"):
            mailbox = factory(combo, None, pipeline_config=definition.get_metadata() if definition else {})
        else:
            mailbox = factory(combo, None)
        
        if body.action == "generate":
            account = mailbox.get_email()
            return {"email": account.email, "account_id": account.account_id}
            
        elif body.action == "wait_code":
            if not body.email:
                raise HTTPException(400, "Missing email for wait_code")
            account = MailboxAccount(email=body.email, account_id=body.account_id)
            # 对于直接创建的驱动，不需要 resolve_mailbox 上下文
            code = mailbox.wait_for_code(account, keyword=body.keyword, timeout=body.timeout)
            return {"code": code}
            
        else:
            raise HTTPException(400, f"Unknown action: {body.action}")
    except Exception as exc:
        raise HTTPException(502, f"{exc.__class__.__name__}: {str(exc)}")
