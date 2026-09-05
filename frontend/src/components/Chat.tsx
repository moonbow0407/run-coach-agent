"use client";

/**
 * 对话流：教练回复时展示执行轨迹（调阅了哪些数据、耗时多少），
 * 让 Agent 的每一步可追溯，而不是黑盒等待。正文来自 response.delta
 * 流式增量（随模型生成逐片段推送，打字机效果）。
 * 支持 Markdown 结构化渲染、智能跟随吸底、打断生成与换新话题。
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { LiveRun } from "@/hooks/useChat";
import { apiPost } from "@/lib/api";
import { CHANGE_TYPE_LABEL } from "@/lib/format";
import type { PendingPlanChangeSummary, ThreadMessage } from "@/lib/types";
import { Eyebrow } from "@/components/ui";
import { Markdown } from "@/components/Markdown";

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
  get_safety_status: "查看安全约束",
  get_unresolved_plan_change: "查看待确认调整",
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
                · {trace.status === "success" || trace.status === "ok" ? "" : `${trace.status} · `}
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
        <div className="mt-2 text-sm leading-relaxed text-asphalt">
          <Markdown content={run.content} />
        </div>
      ) : null}
      {run.error ? (
        <p className="mt-2 text-sm leading-relaxed text-track-deep">
          这轮回复没有完成：{run.error}。可以重发一次。
        </p>
      ) : null}
    </div>
  );
}

function PlanChangeBanner({
  pending,
  actions,
  onDecided,
}: {
  pending: PendingPlanChangeSummary;
  actions: string[];
  onDecided: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canDecide =
    pending.status === "pending_confirmation" &&
    actions.includes("confirm_plan_change") &&
    actions.includes("reject_plan_change");

  const decide = async (action: "confirm" | "reject") => {
    if (!canDecide || busy) return;
    setBusy(true);
    setError(null);
    try {
      await apiPost(`/api/v1/plan-changes/${pending.id}/${action}`);
      onDecided();
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-track/50 bg-track-wash px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-track">
          {canDecide ? "等你确认课表调整" : "课表调整准备中"}
        </p>
        <span className="rounded border border-track/60 bg-paper px-1.5 py-0.5 font-mono text-[10px] font-semibold text-track-deep">
          {CHANGE_TYPE_LABEL[pending.change_type] ?? pending.change_type}
        </span>
        <span className="font-mono text-[10px] text-mist">v{pending.from_plan_version}</span>
      </div>
      <p className="mt-1.5 text-sm leading-relaxed text-asphalt">{pending.reason}</p>
      {pending.session_diffs.length > 0 ? (
        <p className="mt-1 font-mono text-[11px] text-mist">
          影响 {pending.session_diffs.length} 节课
          {pending.session_diffs.slice(0, 3).map((d) => ` · ${d.scheduled_date.slice(5)} ${d.from_type}→${d.to_type}`).join("")}
          {pending.session_diffs.length > 3 ? " …" : ""}
        </p>
      ) : null}
      {error ? <p className="mt-2 text-sm text-track-deep">{error}</p> : null}
      {canDecide ? (
        <div className="mt-2.5 flex gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => void decide("confirm")}
            className="rounded-lg bg-track px-3 py-1.5 text-sm font-medium text-paper transition-colors hover:bg-track-deep disabled:opacity-50"
          >
            采纳调整
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void decide("reject")}
            className="rounded-lg border border-asphalt/30 px-3 py-1.5 text-sm font-medium text-asphalt transition-colors hover:bg-fog disabled:opacity-50"
          >
            保持原计划
          </button>
        </div>
      ) : (
        <p className="mt-1.5 text-xs text-mist">后台定稿完成后会出现确认按钮。</p>
      )}
    </div>
  );
}

export function Chat({
  messages,
  run,
  historyError,
  pendingPlanChange,
  planChangeActions,
  onSend,
  onCancel,
  onNewThread,
  onPlanChangeDecided,
}: {
  messages: ThreadMessage[];
  run: LiveRun;
  historyError: string | null;
  pendingPlanChange: PendingPlanChangeSummary | null;
  planChangeActions: string[];
  onSend: (text: string) => Promise<void>;
  onCancel: () => void;
  onNewThread: () => void;
  onPlanChangeDecided: () => void;
}) {
  const [draft, setDraft] = useState("");
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  // 用户是否向上查阅；为 true 时不强行滚底抢夺视线
  const isUserScrolledUpRef = useRef(false);
  const [showScrollBottomBtn, setShowScrollBottomBtn] = useState(false);
  const scrollRafRef = useRef<number | null>(null);

  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    const scrolledUp = distanceFromBottom > 90;
    isUserScrolledUpRef.current = scrolledUp;
    setShowScrollBottomBtn(scrolledUp);
  }, []);

  const scrollToBottom = useCallback((smooth = false) => {
    isUserScrolledUpRef.current = false;
    setShowScrollBottomBtn(false);
    bottomRef.current?.scrollIntoView({
      behavior: smooth ? "smooth" : "auto",
      block: "end",
    });
  }, []);

  useEffect(() => {
    // 若用户正在往上查阅历史，不自动拉到底部
    if (isUserScrolledUpRef.current) return;
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
    // 发送新消息时自动切回跟随
    isUserScrolledUpRef.current = false;
    setShowScrollBottomBtn(false);
    void onSend(text);
  };

  return (
    <section className="relative flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between px-5 pt-4">
        <Eyebrow>与教练对话</Eyebrow>
        {messages.length > 0 ? (
          <button
            type="button"
            disabled={busy}
            onClick={onNewThread}
            className="font-mono text-[11px] uppercase tracking-wider text-mist transition-colors hover:text-asphalt disabled:opacity-40"
            title="清空当前消息并开启新对话"
          >
            + 开启新话题
          </button>
        ) : null}
      </div>

      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className="thin-scroll mt-3 flex-1 space-y-3 overflow-y-auto px-5 pb-2"
      >
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
              <Markdown content={message.content} />
            </div>
          ),
        )}

        {pendingPlanChange ? (
          <PlanChangeBanner
            pending={pendingPlanChange}
            actions={planChangeActions}
            onDecided={onPlanChangeDecided}
          />
        ) : null}

        {showRun ? <CoachRun run={run} /> : null}
        <div ref={bottomRef} />
      </div>

      {showScrollBottomBtn ? (
        <button
          type="button"
          onClick={() => scrollToBottom(true)}
          className="absolute right-7 bottom-20 z-10 flex items-center gap-1.5 rounded-full border border-hairline bg-paper px-3 py-1 font-mono text-xs font-medium text-asphalt shadow-md transition-transform hover:scale-105"
        >
          <span>↓ 查看最新回复</span>
        </button>
      ) : null}

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
            placeholder={busy ? "教练正在生成回复中…" : "给教练发消息…（Enter 发送）"}
            className="max-h-32 min-h-[42px] flex-1 resize-none rounded-lg border border-hairline bg-paper px-3.5 py-2.5 text-sm leading-relaxed outline-none focus:border-asphalt disabled:opacity-60"
          />
          {busy ? (
            <button
              type="button"
              onClick={onCancel}
              className="h-[42px] shrink-0 rounded-lg border border-track/60 bg-track-wash px-4 text-sm font-medium text-track-deep transition-colors hover:bg-track hover:text-paper"
            >
              停止回复
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={draft.trim() === ""}
              className="h-[42px] shrink-0 rounded-lg bg-asphalt px-4 text-sm font-medium text-paper transition-colors hover:bg-asphalt/85 disabled:opacity-50"
            >
              发送
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
