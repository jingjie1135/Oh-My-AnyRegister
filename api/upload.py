from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from domain.upload_channels import UploadChannelCreateCommand, UploadChannelRecord, UploadChannelUpdateCommand
from infrastructure.upload_channels_repository import UploadChannelsRepository
from infrastructure.accounts_repository import AccountsRepository

from services.upload_services.base_upload import BaseUploader
from services.upload_services.cpa_upload import CpaUploader
from services.upload_services.sub2api_upload import Sub2ApiUploader
from services.upload_services.team_manager_upload import TeamManagerUploader
from services.upload_services.adobe2api_upload import Adobe2ApiUploader
from services.upload_services.flow2api_upload import Flow2ApiUploader

router = APIRouter(prefix="/upload-channels", tags=["upload"])

class ChannelCreateRequest(BaseModel):
    name: str
    channel_type: str
    api_url: str = ""
    api_key: str = ""
    is_enabled: bool = True

class ChannelUpdateRequest(BaseModel):
    name: Optional[str] = None
    channel_type: Optional[str] = None
    api_url: Optional[str] = None
    api_key: Optional[str] = None
    is_enabled: Optional[bool] = None

class BatchUploadRequest(BaseModel):
    account_ids: List[int]
    channel_id: int

def get_uploader(channel_type: str) -> BaseUploader:
    c_type = channel_type.lower()
    if c_type == "cpa":
        return CpaUploader()
    elif c_type in ("sub2api", "new_api"):
        return Sub2ApiUploader()
    elif c_type == "team_manager":
        return TeamManagerUploader()
    elif c_type == "adobe2api":
        return Adobe2ApiUploader()
    elif c_type == "flow2api":
        return Flow2ApiUploader()
    raise ValueError(f"不受支持的上传通道类型: {channel_type}")

@router.get("", response_model=List[UploadChannelRecord])
def list_channels(enabled_only: bool = False):
    repo = UploadChannelsRepository()
    return repo.list_all(enabled_only)

@router.post("", response_model=UploadChannelRecord)
def create_channel(req: ChannelCreateRequest):
    repo = UploadChannelsRepository()
    cmd = UploadChannelCreateCommand(
        name=req.name,
        channel_type=req.channel_type,
        api_url=req.api_url,
        api_key=req.api_key,
        is_enabled=req.is_enabled
    )
    return repo.create(cmd)

@router.put("/{channel_id}", response_model=UploadChannelRecord)
def update_channel(channel_id: int, req: ChannelUpdateRequest):
    repo = UploadChannelsRepository()
    cmd = UploadChannelUpdateCommand(
        name=req.name,
        channel_type=req.channel_type,
        api_url=req.api_url,
        api_key=req.api_key,
        is_enabled=req.is_enabled
    )
    updated = repo.update(channel_id, cmd)
    if not updated:
        raise HTTPException(status_code=404, detail="通道不存在")
    return updated

@router.delete("/{channel_id}")
def delete_channel(channel_id: int):
    repo = UploadChannelsRepository()
    if not repo.delete(channel_id):
         raise HTTPException(status_code=404, detail="通道不存在")
    return {"success": True}

@router.post("/{channel_id}/test", tags=["upload-actions"])
def test_channel_connection(channel_id: int):
    repo = UploadChannelsRepository()
    channel = repo.get_by_id(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="通道不存在")
    
    try:
        uploader = get_uploader(channel.channel_type)
        success, msg = uploader.test_connection(channel)
        return {"success": success, "message": msg}
    except Exception as e:
        return {"success": False, "message": str(e)}

@router.post("/{channel_id}/batch", tags=["upload-actions"])
def batch_upload_accounts(channel_id: int, req: BatchUploadRequest):
    repo = UploadChannelsRepository()
    channel = repo.get_by_id(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="通道不存在")

    account_repo = AccountsRepository()
    accounts = []
    # 这里我们简化，AccountRepository 默认能 get_by_id
    for acc_id in req.account_ids:
        acc = account_repo.get_by_id(acc_id)
        if acc:
            accounts.append(acc)

    try:
        uploader = get_uploader(channel.channel_type)
        result = uploader.upload_accounts(channel, accounts)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
