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

interface WireFrame {
  turn_id?: string;
  thread_id?: string;
  run_id?: string;
  tool?: string;
  call_id?: string;
  status?: string;
  duration_ms?: number;
  content?: string;
  step_index?: number;
  message_id?: string;
  error?: string;
}

function translate(event: string, data: WireFrame): StreamEvent | null {
  switch (event) {
    case "run.started":
      return data.thread_id
        ? { type: "run.started", turnId: data.turn_id ?? "", threadId: data.thread_id }
        : null;
    case "reasoning.started":
      return { type: "reasoning.started" };
    case "tool.started":
      return data.tool && data.call_id
        ? {
            type: "tool.started",
            trace: {
              callId: data.call_id,
              tool: data.tool,
              status: null,
              durationMs: null,
              done: false,
            },
          }
        : null;
    case "tool.completed":
      return data.tool && data.call_id
        ? {
            type: "tool.completed",
            trace: {
              callId: data.call_id,
              tool: data.tool,
              status: data.status ?? null,
              durationMs: data.duration_ms ?? null,
              done: true,
            },
          }
        : null;
    case "response.delta":
      return {
        type: "response.delta",
        content: data.content ?? "",
        stepIndex: data.step_index ?? 0,
      };
    case "run.completed":
      return { type: "run.completed" };
    case "run.failed":
      return { type: "run.failed", error: data.error ?? "执行失败" };
    case "run.cancelled":
      return { type: "run.cancelled" };
    default:
      return null;
  }
}

function parseChunk(buffer: string): { events: Array<{ event: string; data: WireFrame }>; rest: string } {
  const events: Array<{ event: string; data: WireFrame }> = [];
  let rest = buffer;
  let separator = rest.indexOf("\n\n");
  while (separator !== -1) {
    const frame = rest.slice(0, separator);
    rest = rest.slice(separator + 2);
    let event = "message";
    const dataLines: string[] = [];
    for (const line of frame.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
    }
    if (dataLines.length > 0) {
      try {
        events.push({ event, data: JSON.parse(dataLines.join("\n")) as WireFrame });
      } catch {
        // 单帧解析失败只跳过该帧，不中断整个流。
      }
    }
    separator = rest.indexOf("\n\n");
  }
  return { events, rest };
}

/** 发送消息并逐事件回调。resolve 于流正常结束；HTTP/鉴权错误直接抛出。 */
export async function streamChat(
  message: string,
  threadId: string | null,
  onEvent: (event: StreamEvent) => void,
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

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { events, rest } = parseChunk(buffer);
    buffer = rest;
    for (const frame of events) {
      const translated = translate(frame.event, frame.data);
      if (translated) onEvent(translated);
    }
  }
}
