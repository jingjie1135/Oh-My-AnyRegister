from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(slots=True)
class UploadChannelRecord:
    id: int
    name: str
    channel_type: str
    api_url: str = ""
    api_key: str = ""
    is_enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass(slots=True)
class UploadChannelCreateCommand:
    name: str
    channel_type: str
    api_url: str = ""
    api_key: str = ""
    is_enabled: bool = True


@dataclass(slots=True)
class UploadChannelUpdateCommand:
    name: Optional[str] = None
    channel_type: Optional[str] = None
    api_url: Optional[str] = None
    api_key: Optional[str] = None
    is_enabled: Optional[bool] = None
