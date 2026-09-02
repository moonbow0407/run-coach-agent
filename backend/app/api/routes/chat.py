"""聊天 HTTP / SSE 接口：整个系统的传输层入口。

一次请求的完整流转：

    请求 → 鉴权依赖 get_request_context 解析出可信 RequestContext
         → ChatService.send_message 编排一轮对话（建 Turn → 运行 Agent → 提交）
         → /chat 一次性返回最终回答；/chat/stream 通过 SSE 逐步推送执行进度

本层不实现业务规则，失败时只做“应用异常 → HTTP 状态码”的映射。
"""

import asyncio
import logging
from typing import Annotated, Any, AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.agent.application.chat_service import ChatService
from app.agent.lifecycle.dispatcher import LifecycleDispatcher
from app.agent.lifecycle.events import LifecycleEvent, TurnCancelled, TurnCommitted, TurnFailed
from app.agent.ports.conversation_reader import ConversationReader
from app.api.dependencies.context import get_request_context
from app.api.schemas.chat import (
    ChatRequest,
    ChatResponse,
    MessageResponse,
    ThreadMessagesResponse,
)
from app.api.sse import format_sse, map_lifecycle_event
from app.common.errors import (
    AuthenticationError,
    ForbiddenError,
    NotFoundError,
    RunCoachError,
)
from app.identity.application.request_context import RequestContext

router = APIRouter()
logger = logging.getLogger(__name__)


def _chat_service(request: Request) -> ChatService:
    """取出启动时装配在 app.state 上的对话编排服务（一次交互的事务边界）。"""
    return request.app.state.chat_service


def _reader(request: Request) -> ConversationReader:
    """取出会话只读端口；路由只用它查历史，不接触 ORM。"""
    return request.app.state.conversation_reader


def _dispatcher(request: Request) -> LifecycleDispatcher:
    """取出进程内生命周期事件总线，供 SSE 流订阅 / 退订。"""
    return request.app.state.lifecycle


@router.post("/api/v1/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    request_context: Annotated[RequestContext, Depends(get_request_context)],
    request: Request,
) -> ChatResponse:
    """同步聊天接口：等待 Agent 完整执行后一次性返回最终回答。

    request_context 由 Depends 注入：user_id 只来自 JWT，请求体无法指定身份。
    RunCoachError 统一翻译成 HTTP 状态码，避免把内部异常抛给调用方。
    """
    try:
        result = await _chat_service(request).send_message(
            request_context=request_context,
            thread_id=payload.thread_id,
            content=payload.message,
        )
    except RunCoachError as exc:
        raise _http_error(exc) from exc
    return ChatResponse(
        thread_id=result.thread_id,
        turn_id=result.turn_id,
        message_id=result.message_id,
        content=result.content,
    )


@router.post("/api/v1/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    request_context: Annotated[RequestContext, Depends(get_request_context)],
    request: Request,
) -> StreamingResponse:
    """流式聊天接口：通过 SSE 把 Agent 执行进度实时推给前端。

    实现方式：ChatService 的执行放在后台任务里跑，同时把本请求的生命周期
    事件（推理开始 / 能力调用 / 提交 / 失败等）从进程内事件总线转发到 SSE 流。
    事件的生产方是后台任务、消费方是本生成器，两者节奏不同：listener 是同步回调，
    由 ChatService 在执行链里调用；SSE 帧只能在异步生成器里 yield。用 asyncio.Queue
    把“随时可能到达的事件”缓冲起来，才能既不被阻塞又能保证事件按序完整推送。
    """
    queue: asyncio.Queue[LifecycleEvent] = asyncio.Queue()

    def listener(event: LifecycleEvent) -> None:
        # 只接收属于当前 HTTP 请求的事件（按 request_id 过滤），避免不同请求串台。
        if event.request_id == request_context.request_id:
            queue.put_nowait(event)

    dispatcher = _dispatcher(request)
    dispatcher.subscribe(listener)

    async def generate() -> AsyncGenerator[str, Any]:
        # 后台执行一轮对话；本生成器只负责把事件转发成 SSE。
        task = asyncio.create_task(
            _chat_service(request).send_message(
                request_context=request_context,
                thread_id=payload.thread_id,
                content=payload.message,
            )
        )
        queue_task: asyncio.Task[LifecycleEvent] | None = None
        try:
            while True:
                if queue.empty():
                    # 队列暂时为空：同时等待“下一个事件到达”和“整个任务结束”，
                    # 谁先完成就走谁——事件继续转发，任务结束则收尾。
                    queue_task = asyncio.create_task(queue.get())
                    done, _ = await asyncio.wait(
                        {task, queue_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if queue_task in done:
                        event = queue_task.result()
                        queue_task = None
                    else:
                        # 任务先结束：取消“等待事件”的子任务，再处理任务的真实结果。
                        queue_task.cancel()
                        await asyncio.gather(queue_task, return_exceptions=True)
                        queue_task = None
                        # 任务结束的瞬间可能刚好又有事件入队，回到循环先把事件发完。
                        if not queue.empty():
                            continue
                        # 兜底：任务已结束但没等到终态事件（理论上不应发生）。
                        # 仍按任务结果补发收尾 SSE，保证前端一定能收到终态。
                        try:
                            result = task.result()
                        except asyncio.CancelledError:
                            yield format_sse("run.cancelled", {})
                        except Exception as exc:
                            logger.error(
                                "chat.stream.failed_without_terminal_event",
                                exc_info=(type(exc), exc, exc.__traceback__),
                                extra={
                                    "request_id": str(request_context.request_id),
                                    "trace_id": str(request_context.trace_id),
                                    "user_id": str(request_context.user_id),
                                },
                            )
                            yield format_sse("run.failed", {"error": "请求执行失败"})
                        else:
                            yield format_sse(
                                "response.delta",
                                {"content": result.content},
                            )
                            yield format_sse(
                                "run.completed",
                                {
                                    "turn_id": str(result.turn_id),
                                    "run_id": str(result.run_id),
                                    "message_id": str(result.message_id),
                                },
                            )
                        break
                else:
                    # 队列里已有事件：直接取出转发，不阻塞。
                    event = queue.get_nowait()

                mapped = map_lifecycle_event(event)
                if isinstance(event, TurnCommitted):
                    # TurnCommitted 只代表对话已提交，回答内容要等后台任务返回。
                    result = await task
                    yield format_sse("response.delta", {"content": result.content})
                    if mapped:
                        yield format_sse(*mapped)
                    break
                if isinstance(event, (TurnFailed, TurnCancelled)):
                    # 失败 / 取消终态已转发；等后台任务收尾（状态落库由 ChatService 完成）。
                    if mapped:
                        yield format_sse(*mapped)
                    await asyncio.gather(task, return_exceptions=True)
                    break
                if mapped:
                    # 中间过程事件（推理 / 能力调用）原样转发；未映射的事件忽略。
                    yield format_sse(*mapped)
        finally:
            # 生成器结束（含客户端断开）时退订事件并取消后台任务，避免泄漏。
            dispatcher.unsubscribe(listener)
            if queue_task is not None and not queue_task.done():
                queue_task.cancel()
                await asyncio.gather(queue_task, return_exceptions=True)
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    # media_type=text/event-stream 即 SSE（Server-Sent Events，服务器单向推送）响应。
    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/api/v1/threads/{thread_id}/messages", response_model=ThreadMessagesResponse)
async def list_messages(
    thread_id: UUID,
    request_context: Annotated[RequestContext, Depends(get_request_context)],
    request: Request,
) -> ThreadMessagesResponse:
    """查询某个对话线程的历史消息。

    只返回已提交 Turn 中的 user / assistant 消息，且线程必须属于当前用户。
    """
    reader = _reader(request)
    thread = await reader.get_thread(user_id=request_context.user_id, thread_id=thread_id)
    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="对话线程不存在")
    messages = await reader.list_committed_messages(
        user_id=request_context.user_id,
        thread_id=thread_id,
        exclude_turn_id=None,
        limit=200,
    )
    return ThreadMessagesResponse(
        thread_id=thread_id,
        messages=[
            MessageResponse(
                id=message.id,
                role=message.role.value,
                content=message.content,
                created_at=message.created_at.isoformat(),
            )
            for message in messages
        ],
    )


def _http_error(exc: RunCoachError) -> HTTPException:
    """把应用异常族映射为 HTTP 状态码，不向客户端泄漏内部实现细节。"""
    if isinstance(exc, AuthenticationError):
        return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ForbiddenError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
