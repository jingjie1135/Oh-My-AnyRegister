"""
虚拟卡管理 API

路由：
  GET    /virtual-cards              — 列表（脱敏）
  POST   /virtual-cards              — 新增
  PUT    /virtual-cards/{card_id}    — 更新
  DELETE /virtual-cards/{card_id}    — 删除

批量订阅已迁移至 Task 系统：POST /api/tasks/subscribe
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.virtual_card import (
    VirtualCard,
    create_virtual_card,
    delete_virtual_card,
    get_virtual_card,
    list_virtual_cards,
    update_virtual_card,
)

logger = logging.getLogger("subscribe_api")
router = APIRouter(tags=["subscribe"])


# ── 虚拟卡管理 ──────────────────────────────────────────────

class VirtualCardRequest(BaseModel):
    card_number: str
    exp_month: str
    exp_year: str
    cvc: str
    label: str = ""


@router.get("/virtual-cards")
def api_list_virtual_cards():
    """获取所有虚拟卡（脱敏）"""
    return list_virtual_cards()


@router.post("/virtual-cards")
def api_create_virtual_card(body: VirtualCardRequest):
    """创建虚拟卡"""
    card = VirtualCard(
        card_number=body.card_number.strip(),
        exp_month=body.exp_month.strip(),
        exp_year=body.exp_year.strip(),
        cvc=body.cvc.strip(),
        label=body.label.strip(),
    )
    return create_virtual_card(card)


@router.put("/virtual-cards/{card_id}")
def api_update_virtual_card(card_id: int, body: VirtualCardRequest):
    """更新虚拟卡"""
    card = VirtualCard(
        card_number=body.card_number.strip(),
        exp_month=body.exp_month.strip(),
        exp_year=body.exp_year.strip(),
        cvc=body.cvc.strip(),
        label=body.label.strip(),
    )
    result = update_virtual_card(card_id, card)
    if not result:
        raise HTTPException(404, "虚拟卡不存在")
    return result


@router.delete("/virtual-cards/{card_id}")
def api_delete_virtual_card(card_id: int):
    """删除虚拟卡"""
    if not delete_virtual_card(card_id):
        raise HTTPException(404, "虚拟卡不存在")
    return {"ok": True}


# ── 供 task_commands.py 调用的辅助函数 ──────────────────────

def _get_card_full_data(card_id: Optional[int]) -> Optional[dict]:
    """
    根据 card_id 从数据库获取完整的虚拟卡数据（含敏感字段）。
    用于 Task 系统内部传递给订阅处理器。
    """
    if not card_id:
        return None
    card = get_virtual_card(card_id)
    if not card:
        return None
    return {
        "card_number": card.card_number,
        "exp_month": card.exp_month,
        "exp_year": card.exp_year,
        "cvc": card.cvc,
        "label": card.label,
    }
