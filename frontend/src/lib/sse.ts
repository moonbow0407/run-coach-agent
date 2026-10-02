/**
 * SSE 客户端：POST /api/v1/chat/stream 的流式解析。
 *
 * EventSource 无法携带 Authorization 头，这里用 fetch + ReadableStream
 * 手工解析 `event: <名>\\ndata: <json>\\n\\n` 帧（与 backend/app/api/sse.py
 * 的格式对应）。response.delta 是流式正文增量：随模型生成逐片段推送，
 * step_index 标识产生增量的推理步，跨步时应清空缓冲重新累积。
 */

import { ApiError, UnauthorizedError } from "@/lib/api";
import { clearToken, loadToken } from "@/lib/token";

export interface ToolTrace {
  callId: string;
  tool: string;
  status: string | null;
  durationMs: number | null;
  done: boolean;
}

export type StreamEvent =
  | { type: "run.started"; turnId: string; threadId: string }
  | { type: "reasoning.started" }
  | { type: "tool.started"; trace: ToolTrace }
  | { type: "tool.completed"; trace: ToolTrace }
  | { type: "response.delta"; content: string; stepIndex: number }
  | { type: "run.completed" }
  | { type: "run.failed"; error: string }
  | { type: "run.cancelled" };

function protocolError(): Error {
  return new Error("教练响应格式错误，本轮结果未知，请刷新历史确认");
}

function translate(event: string, raw: unknown): StreamEvent {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw protocolError();
  const data = raw as Record<string, unknown>;
  const text = (key: string): string => {
    const value = data[key];
    if (typeof value !== "string" || !value) throw protocolError();
    return value;
  };
  switch (event) {
    case "run.started":
      return { type: event, turnId: text("turn_id"), threadId: text("thread_id") };
    case "reasoning.started":
      return { type: event };
    case "tool.started":
      return { type: event, trace: {
        callId: text("call_id"), tool: text("tool"), status: null, durationMs: null, done: false,
      } };
    case "tool.completed": {
      const duration = data.duration_ms;
      if (typeof duration !== "number" || !Number.isFinite(duration) || duration < 0) {
        throw protocolError();
      }
      return { type: event, trace: {
        callId: text("call_id"), tool: text("tool"), status: text("status"),
        durationMs: duration, done: true,
      } };
    }
    case "response.delta":
      if (typeof data.content !== "string" || typeof data.step_index !== "number"
          || !Number.isInteger(data.step_index) || data.step_index < 0) throw protocolError();
      return { type: event, content: data.content, stepIndex: data.step_index };
    case "run.completed":
    case "run.cancelled":
      return { type: event };
    case "run.failed":
      return { type: event, error: text("error") };
    default:
      throw protocolError();
  }
}

function parseFrame(frame: string): StreamEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  // 注释心跳没有数据，不属于业务事件。
  if (!data.length) {
    if (event !== "message") throw protocolError();
    return null;
  }
  let payload: unknown;
  try {
    payload = JSON.parse(data.join("\n"));
  } catch {
    throw protocolError();
  }
  return translate(event, payload);
}

/** 发送消息并逐事件回调。resolve 于收到明确终态；支持通过 AbortSignal 中断。 */
export async function streamChat(
  message: string,
  threadId: string | null,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const token = loadToken();
  const response = await fetch("/api/v1/chat/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ thread_id: threadId, message }),
    signal,
  });

  if (response.status === 401) {
    clearToken();
    throw new UnauthorizedError();
  }
  if (!response.ok || !response.body) {
    let message = `连接教练失败（${response.status}）`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body?.detail === "string") message = body.detail;
    } catch {
      // 非 JSON 错误体时保留状态码信息。
    }
    throw new ApiError(response.status, message);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) throw new Error("教练连接提前结束，本轮结果未知，请刷新历史确认");
      buffer += decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, "\n");
      let separator: number;
      while ((separator = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, separator);
        buffer = buffer.slice(separator + 2);
        const event = parseFrame(frame);
        if (!event) continue;
        onEvent(event);
        if (["run.completed", "run.failed", "run.cancelled"].includes(event.type)) return;
      }
    }
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    throw new Error(
      error instanceof Error && error.message.includes("本轮结果未知")
        ? error.message : "教练连接中断，本轮结果未知，请刷新历史确认",
      { cause: error },
    );
  } finally {
    try {
      await reader.cancel();
    } catch {
      // 已断开的流可能无法取消；清理失败不得覆盖原始结果。
    }
    reader.releaseLock();
  }
}
