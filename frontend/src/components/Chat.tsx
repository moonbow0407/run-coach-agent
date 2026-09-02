"use client";

/**
 * 对话流：教练回复时展示执行轨迹（调阅了哪些数据、耗时多少），
 * 让 Agent 的每一步可追溯，而不是黑盒等待。正文来自 response.delta
 * 流式增量（随模型生成逐片段推送，打字机效果）。
 */

import { useEffect, useRef, useState } from "react";

import type { LiveRun } from "@/hooks/useChat";
import type { ThreadMessage } from "@/lib/types";
import { Eyebrow } from "@/components/ui";

const TOOL_LABELS: Record<string, string> = {
  search_tools: "查找可用能力",
  get_recent_workouts: "调阅最近的训练",
  get_workout_detail: "查看单次训练",
  get_workout_feedback: "查看训练反馈",
  get_active_goal: "查看训练目标",
  get_active_plan: "查看当前课表",
  get_latest_athlete_state: "查看跑者状态",
  analyze_training_load: "分析训练负荷",
  analyze_workout: "分析训练详情",
  propose_plan_adaptation: "起草课表调整",
};

function toolLabel(tool: string): string {
  return TOOL_LABELS[tool] ?? tool;
}

function CoachRun({ run }: { run: LiveRun }) {
  return (
    <div className="trace-in rounded-lg border border-hairline bg-paper px-4 py-3">
      <ul className="space-y-1">
        {run.traces.map((trace) => (
          <li key={trace.callId} className="font-mono text-xs text-mist">
            <span className="text-track">▸</span> {toolLabel(trace.tool)}
            {trace.done ? (
              <span className="ml-1.5">
                · {trace.status === "ok" ? "" : `${trace.status} · `}
                {trace.durationMs !== null ? `${trace.durationMs}ms` : ""}
              </span>
            ) : (
              <span className="ml-1.5 animate-pulse">…</span>
            )}
          </li>
        ))}
        {run.traces.length === 0 && run.phase === "reasoning" ? (
          <li className="font-mono text-xs text-mist">
            <span className="animate-pulse">教练在思考…</span>
          </li>
        ) : null}
      </ul>
      {run.content ? (
        <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-asphalt">
          {run.content}
        </p>
      ) : null}
      {run.error ? (
        <p className="mt-2 text-sm leading-relaxed text-track-deep">
          这轮回复没有完成：{run.error}。可以重发一次。
        </p>
      ) : null}
    </div>
  );
}

export function Chat({
  messages,
  run,
  historyError,
  onSend,
}: {
  messages: ThreadMessage[];
  run: LiveRun;
  historyError: string | null;
  onSend: (text: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  // 流式正文每个增量都会触发本 effect：用 rAF 合并滚动请求，
  // 一帧最多滚一次，避免逐 token 平滑滚动造成的抖动。
  const scrollRafRef = useRef<number | null>(null);

  useEffect(() => {
    if (scrollRafRef.current !== null) return;
    scrollRafRef.current = requestAnimationFrame(() => {
      scrollRafRef.current = null;
      bottomRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
    });
  }, [messages.length, run.phase, run.content, run.traces.length]);

  useEffect(() => {
    return () => {
      if (scrollRafRef.current !== null) cancelAnimationFrame(scrollRafRef.current);
    };
  }, []);

  const busy = run.phase !== "idle" && run.phase !== "failed";
  const showRun = busy || run.error !== null;
  const submit = () => {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    void onSend(text);
  };

  return (
    <section className="flex min-h-0 flex-1 flex-col">
      <div className="px-5 pt-4">
        <Eyebrow>与教练对话</Eyebrow>
      </div>

      <div className="thin-scroll mt-3 flex-1 space-y-3 overflow-y-auto px-5 pb-2">
        {historyError ? (
          <p className="rounded-lg border border-track/40 bg-track-wash px-4 py-3 text-sm text-track-deep">
            {historyError}
          </p>
        ) : null}
        {messages.length === 0 && !run.content && !historyError ? (
          <div className="rounded-lg border border-dashed border-hairline px-4 py-5">
            <p className="text-sm font-medium text-asphalt">和教练聊聊最近的训练。</p>
            <p className="mt-1 text-sm leading-relaxed text-mist">
              比如：「我最近训练状态怎么样？」或「昨天那个间歇跑崩了，这周后面怎么练？」
            </p>
          </div>
        ) : null}

        {messages.map((message) =>
          message.role === "user" ? (
            <div key={message.id} className="flex justify-end">
              <p className="max-w-[85%] rounded-lg bg-asphalt px-4 py-2.5 text-sm leading-relaxed text-paper">
                {message.content}
              </p>
            </div>
          ) : (
            <div key={message.id} className="max-w-[92%] rounded-lg border border-hairline bg-paper px-4 py-3">
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-asphalt">
                {message.content}
              </p>
            </div>
          ),
        )}

        {showRun ? <CoachRun run={run} /> : null}
        <div ref={bottomRef} />
      </div>

      <div className="border-t border-hairline px-5 py-3.5">
        <div className="flex items-end gap-2">
          <textarea
            rows={1}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                submit();
              }
            }}
            placeholder="给教练发消息…（Enter 发送）"
            className="max-h-32 min-h-[42px] flex-1 resize-none rounded-lg border border-hairline bg-paper px-3.5 py-2.5 text-sm leading-relaxed outline-none focus:border-asphalt disabled:opacity-60"
          />
          <button
            type="button"
            onClick={submit}
            disabled={busy || draft.trim() === ""}
            className="h-[42px] shrink-0 rounded-lg bg-asphalt px-4 text-sm font-medium text-paper transition-colors hover:bg-asphalt/85 disabled:opacity-50"
          >
            {busy ? "教练正在回复…" : "发送"}
          </button>
        </div>
      </div>
    </section>
  );
}
