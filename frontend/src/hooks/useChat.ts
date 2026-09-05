"use client";

/**
 * 对话流状态：历史装载、发送（SSE）、运行中的轨迹与阶段。
 *
 * 一轮运行的可视化状态机：
 *   idle → sending → reasoning →(tool.started/completed 追加轨迹)→
 *   response.delta 逐片段累积正文 → run.completed / run.failed / run.cancelled
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, apiGet, UnauthorizedError } from "@/lib/api";
import type { PendingPlanChangeSummary, ThreadMessage } from "@/lib/types";
import { clearThreadId, loadThreadId, saveThreadId } from "@/lib/token";
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
  stepIndex: number; // 当前正文所属的推理步；跨步意味着缓冲要清空重积
  error: string | null;
}

const IDLE_RUN: LiveRun = { phase: "idle", traces: [], content: "", stepIndex: 0, error: null };

export function useChat(
  enabled: boolean,
  onRunCompleted: () => void,
  onUnauthorized: () => void,
) {
  const [threadId, setThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ThreadMessage[]>([]);
  const [run, setRun] = useState<LiveRun>(IDLE_RUN);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [pendingPlanChange, setPendingPlanChange] = useState<PendingPlanChangeSummary | null>(null);
  const [planChangeActions, setPlanChangeActions] = useState<string[]>([]);
  // 同一轮运行期间可能重复触发 onRunCompleted 的保护由调用方决定，这里只保证回调最新。
  const completedRef = useRef(onRunCompleted);
  completedRef.current = onRunCompleted;
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const existing = loadThreadId();
    setThreadId(existing);
    // 尚无会话：不要请求 /threads//messages（会 422），保持干净空态。
    if (!existing) {
      setMessages([]);
      setHistoryError(null);
      return;
    }
    apiGet<{ thread_id: string; messages: ThreadMessage[] }>(
      `/api/v1/threads/${existing}/messages`,
    )
      .then((data) => {
        setMessages(data.messages);
        setThreadId(data.thread_id);
        saveThreadId(data.thread_id);
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 404) {
          // 本地存的 thread 已失效：清空后由首条消息重新创建。
          setMessages([]);
          return;
        }
        if (error instanceof UnauthorizedError) {
          onUnauthorized();
          return;
        }
        setHistoryError(error instanceof Error ? error.message : "无法读取对话历史");
      });
  }, [enabled, onUnauthorized]);

  const cancel = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
  }, []);

  const startNewThread = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    clearThreadId();
    setThreadId(null);
    setMessages([]);
    setRun(IDLE_RUN);
    setHistoryError(null);
    setPendingPlanChange(null);
    setPlanChangeActions([]);
  }, []);

  const send = useCallback(
    async (text: string) => {
      const content = text.trim();
      if (!content || (run.phase !== "idle" && run.phase !== "failed")) return;
      setMessages((prev) => [
        ...prev,
        { id: `local-${Date.now()}`, role: "user", content, created_at: new Date().toISOString() },
      ]);
      setRun({ phase: "sending", traces: [], content: "", stepIndex: 0, error: null });

      const controller = new AbortController();
      abortControllerRef.current = controller;

      // 流式正文快照与完成标记：与下方 setRun 同一累积规则维护，
      // 供「流成功但历史重取失败」时把回复转正为本地消息兜底。
      let streamedContent = "";
      let streamedStep = -1;
      let runCompleted = false;

      const handle = (event: StreamEvent) => {
        if (event.type === "response.delta") {
          streamedContent =
            streamedStep === event.stepIndex
              ? streamedContent + event.content
              : event.content;
          streamedStep = event.stepIndex;
        }
        if (event.type === "run.completed") {
          runCompleted = true;
          setPendingPlanChange(event.pendingPlanChange);
          setPlanChangeActions(event.actions);
        }
        // 线程 id 落库是副作用，必须放在 updater 之外：updater 要保持纯函数。
        if (event.type === "run.started") {
          saveThreadId(event.threadId);
          setThreadId(event.threadId);
        }
        setRun((prev) => {
          switch (event.type) {
            case "run.started":
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
              return {
                ...prev,
                phase: "responding",
                // 逐片段打字机累积；step_index 变化说明上一段是工具步骤的
                // 附带文本（不落库），清空缓冲重新累积最终回答。
                content:
                  prev.stepIndex === event.stepIndex
                    ? prev.content + event.content
                    : event.content,
                stepIndex: event.stepIndex,
              };
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
        await streamChat(content, threadId, handle, controller.signal);
        // 流正常结束且已提交：重取历史，把本地乐观消息换成落库消息。
        // 先落库消息，再清空 live run，避免 finally 抢先擦掉正文造成闪烁。
        const current = loadThreadId();
        if (current) {
          try {
            const data = await apiGet<{ thread_id: string; messages: ThreadMessage[] }>(
              `/api/v1/threads/${current}/messages`,
            );
            setMessages(data.messages);
          } catch {
            // 重取失败不算整轮失败：回复已生成，把流式正文转正为本地消息兜底展示。
            if (runCompleted && streamedContent) {
              setMessages((prev) => [
                ...prev,
                {
                  id: `local-${Date.now()}`,
                  role: "assistant",
                  content: streamedContent,
                  created_at: new Date().toISOString(),
                },
              ]);
            }
          }
        }
        setRun((prev) => (prev.phase === "failed" ? prev : IDLE_RUN));
      } catch (error) {
        if (error instanceof Error && error.name === "AbortError") {
          setRun((prev) => ({
            ...prev,
            phase: "failed",
            error: "你已停止了教练的回复",
          }));
          return;
        }
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
        abortControllerRef.current = null;
      }
    },
    [run.phase, threadId, onUnauthorized],
  );

  const clearPendingPlanChange = useCallback(() => {
    setPendingPlanChange(null);
    setPlanChangeActions([]);
  }, []);

  return {
    threadId,
    messages,
    run,
    historyError,
    pendingPlanChange,
    planChangeActions,
    clearPendingPlanChange,
    send,
    cancel,
    startNewThread,
  };
}
