import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.agent.application.chat_service import ChatService
from app.agent.lifecycle.dispatcher import LifecycleDispatcher
from app.agent.lifecycle.events import LifecycleEvent, TurnCommitted, TurnFailed, TurnCancelled
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


def _chat_service(request: Request) -> ChatService:
    return request.app.state.chat_service


def _reader(request: Request) -> ConversationReader:
    return request.app.state.conversation_reader


def _dispatcher(request: Request) -> LifecycleDispatcher:
    return request.app.state.lifecycle


@router.post("/api/v1/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    request_context: Annotated[RequestContext, Depends(get_request_context)],
    request: Request,
) -> ChatResponse:
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
    queue: asyncio.Queue[LifecycleEvent] = asyncio.Queue()

    def listener(event: LifecycleEvent) -> None:
        if event.request_id == request_context.request_id:
            queue.put_nowait(event)

    dispatcher = _dispatcher(request)
    dispatcher.subscribe(listener)

    async def generate() -> object:
        task = asyncio.create_task(
            _chat_service(request).send_message(
                request_context=request_context,
                thread_id=payload.thread_id,
                content=payload.message,
            )
        )
        try:
            while True:
                event = await queue.get()
                mapped = map_lifecycle_event(event)
                if isinstance(event, TurnCommitted):
                    result = await task
                    yield format_sse("response.delta", {"content": result.content})
                    if mapped:
                        yield format_sse(*mapped)
                    break
                if isinstance(event, (TurnFailed, TurnCancelled)):
                    if mapped:
                        yield format_sse(*mapped)
                    try:
                        await task
                    except (Exception, asyncio.CancelledError):
                        pass
                    break
                if mapped:
                    yield format_sse(*mapped)
        finally:
            dispatcher.unsubscribe(listener)
            if not task.done():
                task.cancel()

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/api/v1/threads/{thread_id}/messages", response_model=ThreadMessagesResponse)
async def list_messages(
    thread_id: UUID,
    request_context: Annotated[RequestContext, Depends(get_request_context)],
    request: Request,
) -> ThreadMessagesResponse:
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
    if isinstance(exc, AuthenticationError):
        return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ForbiddenError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
