"""
虚拟卡管理与随机地址生成模块

- 虚拟卡存储在 provider_settings 表中 (provider_type='payment', provider_key='virtual_card_<id>')
- 地址生成参考了 codex-console 的 random_billing.py 本地生成策略
"""
from __future__ import annotations

import json
import random
import re
import uuid
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

from sqlmodel import Session, select

from core.db import ProviderSettingModel, engine


# ── 数据结构 ────────────────────────────────────────────────────

@dataclass
class VirtualCard:
    """虚拟卡信息"""
    card_number: str   # 16位卡号
    exp_month: str     # MM
    exp_year: str      # YY 或 YYYY
    cvc: str           # 3-4位安全码
    label: str = ""    # 用户自定义标签（如 "主力卡"）

    def masked_number(self) -> str:
        """脱敏卡号，仅显示后4位"""
        digits = re.sub(r"\D", "", self.card_number)
        if len(digits) <= 4:
            return digits
        return f"****{digits[-4:]}"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BillingAddress:
    """账单地址"""
    first_name: str
    last_name: str
    line1: str           # 街道地址
    city: str
    state: str           # 州代码（如 CA）
    postal_code: str     # 邮编
    country: str = "US"  # 国家代码

    def to_dict(self) -> dict:
        return asdict(self)


# ── 美国地址随机生成（迁移自 codex-console random_billing.py）──

FIRST_NAMES = [
    "James", "Olivia", "Noah", "Emma", "Liam", "Sophia", "Ethan",
    "Mia", "Aiden", "Ava", "Lucas", "Amelia", "Henry", "Harper",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
    "Miller", "Davis", "Wilson", "Anderson", "Taylor", "Thomas",
]

STREET_SUFFIXES = ["St", "Ave", "Blvd", "Dr", "Ln", "Way", "Ct", "Pl", "Rd"]

STREET_BASES = [
    "Washington", "Lincoln", "Franklin", "Jefferson", "Madison",
    "Jackson", "Lake", "Hill", "Sunset", "Park", "Riverside",
    "Highland", "Center", "Valley", "Cedar", "Pine", "Maple",
    "Willow", "Cherry", "Elm", "Meadow",
]

# 美国28州城市池 — 每个州包含城市列表和邮编前缀
US_STATE_POOL: Dict[str, Dict] = {
    "CA": {"name": "California", "cities": ["Los Angeles", "San Francisco", "San Diego", "San Jose"], "zip_prefix": "9"},
    "NY": {"name": "New York", "cities": ["New York", "Brooklyn", "Buffalo", "Rochester"], "zip_prefix": "1"},
    "TX": {"name": "Texas", "cities": ["Houston", "Dallas", "Austin", "San Antonio"], "zip_prefix": "7"},
    "FL": {"name": "Florida", "cities": ["Miami", "Orlando", "Tampa", "Jacksonville"], "zip_prefix": "3"},
    "WA": {"name": "Washington", "cities": ["Seattle", "Spokane", "Tacoma", "Bellevue"], "zip_prefix": "9"},
    "IL": {"name": "Illinois", "cities": ["Chicago", "Aurora", "Naperville", "Rockford"], "zip_prefix": "6"},
    "PA": {"name": "Pennsylvania", "cities": ["Philadelphia", "Pittsburgh", "Allentown", "Erie"], "zip_prefix": "1"},
    "OH": {"name": "Ohio", "cities": ["Columbus", "Cleveland", "Cincinnati", "Toledo"], "zip_prefix": "4"},
    "GA": {"name": "Georgia", "cities": ["Atlanta", "Savannah", "Augusta", "Macon"], "zip_prefix": "3"},
    "NC": {"name": "North Carolina", "cities": ["Charlotte", "Raleigh", "Greensboro", "Durham"], "zip_prefix": "2"},
    "VA": {"name": "Virginia", "cities": ["Virginia Beach", "Richmond", "Norfolk", "Arlington"], "zip_prefix": "2"},
    "MA": {"name": "Massachusetts", "cities": ["Boston", "Worcester", "Cambridge", "Springfield"], "zip_prefix": "0"},
    "NJ": {"name": "New Jersey", "cities": ["Newark", "Jersey City", "Paterson", "Edison"], "zip_prefix": "0"},
    "MI": {"name": "Michigan", "cities": ["Detroit", "Grand Rapids", "Lansing", "Ann Arbor"], "zip_prefix": "4"},
    "AZ": {"name": "Arizona", "cities": ["Phoenix", "Tucson", "Mesa", "Chandler"], "zip_prefix": "8"},
    "CO": {"name": "Colorado", "cities": ["Denver", "Colorado Springs", "Aurora", "Fort Collins"], "zip_prefix": "8"},
    "NV": {"name": "Nevada", "cities": ["Las Vegas", "Reno", "Henderson", "North Las Vegas"], "zip_prefix": "8"},
    "OR": {"name": "Oregon", "cities": ["Portland", "Salem", "Eugene", "Gresham"], "zip_prefix": "9"},
    "MN": {"name": "Minnesota", "cities": ["Minneapolis", "Saint Paul", "Rochester", "Bloomington"], "zip_prefix": "5"},
    "MO": {"name": "Missouri", "cities": ["Kansas City", "St. Louis", "Springfield", "Columbia"], "zip_prefix": "6"},
    "TN": {"name": "Tennessee", "cities": ["Nashville", "Memphis", "Knoxville", "Chattanooga"], "zip_prefix": "3"},
    "IN": {"name": "Indiana", "cities": ["Indianapolis", "Fort Wayne", "Evansville", "South Bend"], "zip_prefix": "4"},
    "WI": {"name": "Wisconsin", "cities": ["Milwaukee", "Madison", "Green Bay", "Kenosha"], "zip_prefix": "5"},
    "MD": {"name": "Maryland", "cities": ["Baltimore", "Columbia", "Germantown", "Rockville"], "zip_prefix": "2"},
    "SC": {"name": "South Carolina", "cities": ["Charleston", "Columbia", "Greenville", "Myrtle Beach"], "zip_prefix": "2"},
    "AL": {"name": "Alabama", "cities": ["Birmingham", "Montgomery", "Huntsville", "Mobile"], "zip_prefix": "3"},
    "OK": {"name": "Oklahoma", "cities": ["Oklahoma City", "Tulsa", "Norman", "Edmond"], "zip_prefix": "7"},
    "UT": {"name": "Utah", "cities": ["Salt Lake City", "Provo", "West Valley City", "Ogden"], "zip_prefix": "8"},
}


def generate_random_address() -> BillingAddress:
    """生成随机美国账单地址"""
    # 随机选择州
    state_code, state_info = random.choice(list(US_STATE_POOL.items()))
    city = random.choice(state_info["cities"])

    # 生成街道地址
    number = random.randint(18, 9999)
    base = random.choice(STREET_BASES)
    suffix = random.choice(STREET_SUFFIXES)
    line1 = f"{number} {base} {suffix}"
    # 28% 概率添加公寓号
    if random.random() < 0.28:
        line1 += f" Apt {random.randint(1, 999)}"

    # 生成邮编（前缀 + 4位随机数）
    zip_prefix = state_info.get("zip_prefix", "9")
    postal_code = f"{zip_prefix}{random.randint(0, 9999):04d}"

    return BillingAddress(
        first_name=random.choice(FIRST_NAMES),
        last_name=random.choice(LAST_NAMES),
        line1=line1,
        city=city,
        state=state_code,
        postal_code=postal_code,
        country="US",
    )


# ── 虚拟卡 CRUD（基于 ProviderSettingModel）────────────────────

_PROVIDER_TYPE = "payment"
_KEY_PREFIX = "virtual_card_"


def _card_to_setting(card: VirtualCard, setting_id: Optional[int] = None) -> ProviderSettingModel:
    """将虚拟卡转换为 ProviderSettingModel"""
    key = f"{_KEY_PREFIX}{uuid.uuid4().hex[:8]}"
    setting = ProviderSettingModel(
        provider_type=_PROVIDER_TYPE,
        provider_key=key,
        display_name=card.label or f"卡 {card.masked_number()}",
        enabled=True,
    )
    if setting_id:
        setting.id = setting_id
    setting.set_config(card.to_dict())
    return setting


def _setting_to_card(setting: ProviderSettingModel) -> dict:
    """将 ProviderSettingModel 转换为前端友好的卡信息"""
    cfg = setting.get_config()
    return {
        "id": setting.id,
        "provider_key": setting.provider_key,
        "label": cfg.get("label") or setting.display_name,
        "masked_number": VirtualCard(**{k: cfg.get(k, "") for k in ["card_number", "exp_month", "exp_year", "cvc", "label"]}).masked_number(),
        "exp_month": cfg.get("exp_month", ""),
        "exp_year": cfg.get("exp_year", ""),
        "enabled": setting.enabled,
        "created_at": setting.created_at.isoformat() if setting.created_at else None,
    }


def list_virtual_cards() -> List[dict]:
    """获取所有虚拟卡列表（脱敏）"""
    with Session(engine) as session:
        stmt = select(ProviderSettingModel).where(
            ProviderSettingModel.provider_type == _PROVIDER_TYPE,
            ProviderSettingModel.provider_key.startswith(_KEY_PREFIX),
        )
        settings = session.exec(stmt).all()
        return [_setting_to_card(s) for s in settings]


def get_virtual_card(card_id: int) -> Optional[VirtualCard]:
    """根据 ID 获取虚拟卡完整信息（含敏感数据）"""
    with Session(engine) as session:
        setting = session.get(ProviderSettingModel, card_id)
        if not setting or setting.provider_type != _PROVIDER_TYPE:
            return None
        cfg = setting.get_config()
        return VirtualCard(
            card_number=cfg.get("card_number", ""),
            exp_month=cfg.get("exp_month", ""),
            exp_year=cfg.get("exp_year", ""),
            cvc=cfg.get("cvc", ""),
            label=cfg.get("label", ""),
        )


def create_virtual_card(card: VirtualCard) -> dict:
    """创建虚拟卡"""
    with Session(engine) as session:
        setting = _card_to_setting(card)
        session.add(setting)
        session.commit()
        session.refresh(setting)
        return _setting_to_card(setting)


def update_virtual_card(card_id: int, card: VirtualCard) -> Optional[dict]:
    """更新虚拟卡"""
    with Session(engine) as session:
        setting = session.get(ProviderSettingModel, card_id)
        if not setting or setting.provider_type != _PROVIDER_TYPE:
            return None
        setting.display_name = card.label or f"卡 {card.masked_number()}"
        setting.set_config(card.to_dict())
        session.add(setting)
        session.commit()
        session.refresh(setting)
        return _setting_to_card(setting)


def delete_virtual_card(card_id: int) -> bool:
    """删除虚拟卡"""
    with Session(engine) as session:
        setting = session.get(ProviderSettingModel, card_id)
        if not setting or setting.provider_type != _PROVIDER_TYPE:
            return False
        session.delete(setting)
        session.commit()
        return True
