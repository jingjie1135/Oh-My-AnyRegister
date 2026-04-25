from __future__ import annotations

from typing import Optional, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from application.task_commands import TaskCommandsService
from application.tasks_query import TasksQueryService

router = APIRouter(prefix="/tasks", tags=["task-commands"])
command_service = TaskCommandsService()
query_service = TasksQueryService()


class RegisterTaskRequest(BaseModel):
    platform: str
    email: Optional[str] = None
    password: Optional[str] = None
    count: int = 1
    concurrency: int = 1
    proxy: Optional[str] = None
    executor_type: str = "protocol"
    captcha_solver: str = "auto"
    extra: dict = Field(default_factory=dict)


class SubscribeTaskRequest(BaseModel):
    """批量订阅任务请求"""
    platform: str = "adobe"
    account_ids: List[int] = Field(default_factory=list)
    card_id: Optional[int] = None  # 虚拟卡 ID，从数据库获取完整卡信息
    headless: bool = True  # 是否使用 headless 浏览器


@router.post("/register")
def create_register_task(body: RegisterTaskRequest):
    return command_service.create_register_task(body.model_dump())


@router.post("/subscribe")
def create_subscribe_task(body: SubscribeTaskRequest):
    """创建批量订阅任务"""
    from application.tasks import create_subscribe_task as _create
    from api.subscribe import _get_card_full_data

    # 获取完整的卡信息
    card_data = _get_card_full_data(body.card_id) if body.card_id else None
    if not card_data:
        raise HTTPException(400, "未找到有效的虚拟卡，请先在设置中添加虚拟卡")

    payload = {
        "platform": body.platform,
        "account_ids": body.account_ids,
        "card": card_data,
        "headless": body.headless,
    }
    task = _create(payload)

    # 唤醒 TaskRuntime 调度器
    from services.task_runtime import task_runtime
    task_runtime.wake_up()

    return task


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str):
    task = command_service.cancel_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@router.get("/{task_id}/logs/stream")
async def stream_logs(task_id: str, since: int = 0):
    if not query_service.get_task(task_id):
        raise HTTPException(404, "任务不存在")
    return StreamingResponse(
        command_service.stream_task_events(task_id, since=since),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

