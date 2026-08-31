"use client";

/**
 * 对话流状态：历史装载、发送（SSE）、运行中的轨迹与阶段。
 *
 * 一轮运行的可视化状态机：
 *   idle → sending → reasoning →(tool.started/completed 追加轨迹)→
 *   response.delta 落正文 → run.completed / run.failed / run.cancelled
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, apiGet, UnauthorizedError } from "@/lib/api";
import type { ThreadMessage } from "@/lib/types";
import { loadThreadId, saveThreadId } from "@/lib/token";
import { streamChat, type StreamEvent, type ToolTrace } from "@/lib/sse";

export type RunPhase =
  | "idle"
  | "sending"
  | "reasoning"
  | "responding"
  | "failed";

export interface LiveRun {
  phase: RunPhase;
  traces: ToolTrace[];
  content: string;
  error: string | null;
}

const IDLE_RUN: LiveRun = { phase: "idle", traces: [], content: "", error: null };

export function useChat(
  enabled: boolean,
  onRunCompleted: () => void,
  onUnauthorized: () => void,
) {
  const [threadId, setThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ThreadMessage[]>([]);
  const [run, setRun] = useState<LiveRun>(IDLE_RUN);
  const [historyError, setHistoryError] = useState<string | null>(null);
  // 同一轮运行期间可能重复触发 onRunCompleted 的保护由调用方决定，这里只保证回调最新。
  const completedRef = useRef(onRunCompleted);
  completedRef.current = onRunCompleted;

  useEffect(() => {
    if (!enabled) return;
    const existing = loadThreadId();
    setThreadId(existing);
    apiGet<{ thread_id: string; messages: ThreadMessage[] }>(
      `/api/v1/threads/${existing ?? ""}/messages`,
    )
      .then((data) => {
        setMessages(data.messages);
        setThreadId(data.thread_id);
        saveThreadId(data.thread_id);
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 404) {
          // 还没有会话线程：正常空状态，首条消息发出后由后端创建。
          setMessages([]);
          return;
        }
        setHistoryError(error instanceof Error ? error.message : "无法读取对话历史");
      });
  }, [enabled]);

  const startNewThread = useCallback(() => {
    window.localStorage.removeItem("run-coach.thread-id");
    setThreadId(null);
    setMessages([]);
    setRun(IDLE_RUN);
    setHistoryError(null);
  }, []);

  const send = useCallback(
    async (text: string) => {
      const content = text.trim();
      if (!content || run.phase !== "idle") return;
      setMessages((prev) => [
        ...prev,
        { id: `local-${Date.now()}`, role: "user", content, created_at: new Date().toISOString() },
      ]);
      setRun({ phase: "sending", traces: [], content: "", error: null });

      const handle = (event: StreamEvent) => {
        setRun((prev) => {
          switch (event.type) {
            case "run.started":
              saveThreadId(event.threadId);
              setThreadId(event.threadId);
              return { ...prev, phase: "reasoning" };
            case "reasoning.started":
              return { ...prev, phase: "reasoning" };
            case "tool.started":
              return { ...prev, traces: [...prev.traces, event.trace] };
            case "tool.completed":
              return {
                ...prev,
                traces: prev.traces.map((trace) =>
                  trace.callId === event.trace.callId ? event.trace : trace,
                ),
              };
            case "response.delta":
              return { ...prev, phase: "responding", content: prev.content + event.content };
            case "run.completed":
              return { ...prev, phase: "idle" };
            case "run.failed":
              return { ...prev, phase: "failed", error: event.error };
            case "run.cancelled":
              return { ...prev, phase: "failed", error: "这一轮回复被取消了" };
            default:
              return prev;
          }
        });
        if (event.type === "run.completed") {
          // 用 setTimeout 脱离 setState 批处理，再取落库后的最终消息列表。
          window.setTimeout(() => void completedRef.current(), 0);
        }
      };

      try {
        await streamChat(content, threadId, handle);
        // 流正常结束且已提交：重取历史，把本地乐观消息换成落库消息。
        const current = loadThreadId();
        if (current) {
          const data = await apiGet<{ thread_id: string; messages: ThreadMessage[] }>(
            `/api/v1/threads/${current}/messages`,
          );
          setMessages(data.messages);
        }
      } catch (error) {
        if (error instanceof UnauthorizedError) {
          onUnauthorized();
          return;
        }
        setRun((prev) => ({
          ...prev,
          phase: "failed",
          error: error instanceof Error ? error.message : "连接教练失败",
        }));
      } finally {
        setRun((prev) => (prev.phase === "failed" ? prev : IDLE_RUN));
      }
    },
    [run.phase, threadId, onUnauthorized],
  );

  return { threadId, messages, run, historyError, send, startNewThread };
}
