"use client";

/**
 * 签名元素：本周课表负荷剖面条。
 *
 * 七天一根柱，高度按课型负荷分级；教练的调整提案以「红铅笔批注」
 * 画在受影响的课次上（旧安排划掉 → 箭头 → 新安排），下方是要你
 * 决定的提案卡。采纳后课表换新版本，版本号以盖章动效落下。
 */

import { useState } from "react";

import { apiPost } from "@/lib/api";
import {
  SESSION_LABEL,
  SESSION_LOAD,
  SESSION_NAME,
  formatDayMonth,
  formatPrescription,
  parseDate,
} from "@/lib/format";
import type { ActivePlan, PlanChange, PlannedSession } from "@/lib/types";
import { EmptyState, ErrorNote, Eyebrow } from "@/components/ui";

const WEEKDAY_LABELS = ["一", "二", "三", "四", "五", "六", "日"] as const;

interface DayCell {
  date: string;
  weekday: string;
  session: PlannedSession | null;
  change: PlanChange["payload"]["changes"][number] | null;
}

function buildWeek(plan: ActivePlan, pendingChange: PlanChange | null): DayCell[] {
  const start = parseDate(plan.window_start);
  const sessionsByDate = new Map<string, PlannedSession>();
  for (const session of plan.sessions) {
    if (!sessionsByDate.has(session.scheduled_date)) {
      sessionsByDate.set(session.scheduled_date, session);
    }
  }
  const changeBySessionId = new Map<string, PlanChange["payload"]["changes"][number]>();
  if (pendingChange) {
    for (const change of pendingChange.payload.changes) {
      changeBySessionId.set(change.source_session_id, change);
    }
  }

  return Array.from({ length: 7 }, (_, index) => {
    const day = new Date(start);
    day.setDate(start.getDate() + index);
    const date = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
    const session = sessionsByDate.get(date) ?? null;
    return {
      date,
      weekday: WEEKDAY_LABELS[day.getDay() === 0 ? 6 : day.getDay() - 1] ?? "",
      session,
      change: session ? (changeBySessionId.get(session.id) ?? null) : null,
    };
  });
}

function LoadBar({ cell, index }: { cell: DayCell; index: number }) {
  const change = cell.change;
  const hasPending = change !== null;
  const loadType = change ? change.to_type : (cell.session?.session_type ?? "rest");
  const height = hasPending || cell.session ? SESSION_LOAD[loadType] : 0.04;
  const barColor = hasPending ? "bg-track" : cell.session ? "bg-asphalt" : "bg-hairline";
  // 负荷百分比高度：容器固定高，柱子按等级撑起。
  const heightPercent = Math.round(height * 100);

  return (
    <div
      className="bar-grow flex h-20 items-end justify-center"
      style={{ animationDelay: `${index * 60}ms` }}
    >
      <div
        className={`w-5 rounded-sm ${barColor} ${hasPending ? "shadow-[inset_0_0_0_1.5px_var(--color-paper)]" : ""}`}
        style={{ height: `${Math.max(heightPercent, 6)}%` }}
        aria-hidden
      />
    </div>
  );
}

function DayLabel({ cell }: { cell: DayCell }) {
  if (cell.change) {
    return (
      <div className="flex flex-col items-center gap-0.5">
        <span className="font-mono text-[10px] text-mist line-through decoration-track">
          {SESSION_LABEL[cell.change.from_type]}
        </span>
        <span className="pencil-underline font-mono text-[11px] font-semibold text-track">
          {SESSION_LABEL[cell.change.to_type]}
        </span>
      </div>
    );
  }
  if (cell.session) {
    return (
      <span className="font-mono text-[11px] font-medium text-asphalt">
        {SESSION_LABEL[cell.session.session_type]}
      </span>
    );
  }
  return <span className="font-mono text-[11px] text-hairline">·</span>;
}

export function WeekPlan({
  plan,
  pendingChange,
  onDecided,
  onRefresh,
}: {
  plan: ActivePlan | null;
  pendingChange: PlanChange | null;
  onDecided: () => Promise<void>;
  onRefresh: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!plan) {
    return (
      <section className="rounded-xl border border-hairline bg-paper p-4">
        <Eyebrow>本周课表</Eyebrow>
        <div className="mt-3">
          <EmptyState
            title="教练还没有为你排课"
            hint="和教练聊聊你的目标，第一份课表会出现在这里。"
          />
        </div>
      </section>
    );
  }

  const pendingDecision =
    pendingChange?.status === "pending_confirmation" ? pendingChange : null;
  const week = buildWeek(plan, pendingDecision);
  const decisions = pendingDecision?.payload.changes ?? [];
  const isPreparing = pendingChange?.status === "draft";

  const decide = async (action: "confirm" | "reject") => {
    if (!pendingDecision || busy) return;
    setBusy(true);
    setError(null);
    try {
      await apiPost(`/api/v1/plan-changes/${pendingDecision.id}/${action}`);
      await onDecided();
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-xl border border-hairline bg-paper p-4">
      <div className="flex items-center justify-between">
        <Eyebrow>本周课表</Eyebrow>
        <span
          key={plan.plan.version}
          className="stamp-in rounded border border-asphalt/70 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-asphalt"
        >
          v{plan.plan.version}
        </span>
      </div>

      <div className="mt-4 grid grid-cols-7 gap-1">
        {week.map((cell, index) => (
          <div key={cell.date} className="flex flex-col items-center gap-1.5">
            <span className="font-mono text-[10px] uppercase tracking-wider text-mist">
              {cell.weekday}
            </span>
            <LoadBar cell={cell} index={index} />
            <DayLabel cell={cell} />
            <span className="font-mono text-[10px] text-mist">
              {formatDayMonth(cell.date)}
            </span>
          </div>
        ))}
      </div>

      {isPreparing ? (
        <div className="mt-4 rounded-lg border border-hairline bg-fog p-3.5">
          <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-mist">
            调整准备中
          </p>
          <p className="mt-1.5 text-sm leading-relaxed text-mist">
            教练的建议正在准备确认，按钮会在后台处理完成后出现。
          </p>
        </div>
      ) : pendingDecision ? (
        <div className="mt-4 rounded-lg border border-track/50 bg-track-wash p-3.5">
          <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-track">
            等你的决定 · 红铅笔批注
          </p>
          <p className="mt-1.5 text-sm font-medium text-asphalt">
            教练建议下调未来 {pendingDecision.payload.horizon_days} 天的负荷
          </p>
          <p className="mt-1 text-sm leading-relaxed text-mist">{pendingDecision.reason}</p>

          <ul className="mt-3 space-y-1.5">
            {decisions.map((change) => (
              <li key={change.source_session_id} className="text-sm leading-snug">
                <span className="font-mono text-xs text-mist">
                  {formatDayMonth(change.scheduled_date)}
                </span>
                <span className="mx-1.5 text-mist line-through">
                  {SESSION_NAME[change.from_type]}
                </span>
                <span className="text-mist">→</span>
                <span className="mx-1.5 font-medium text-track-deep">
                  {SESSION_NAME[change.to_type]}
                </span>
                {formatPrescription(change.new_prescription) ? (
                  <span className="ml-1 font-mono text-xs text-mist">
                    {formatPrescription(change.new_prescription)}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>

          {error ? (
            <div className="mt-3">
              <ErrorNote message={error} onRetry={onRefresh} />
            </div>
          ) : null}

          <div className="mt-3 flex gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => void decide("confirm")}
              className="rounded-lg bg-track px-3.5 py-2 text-sm font-medium text-paper transition-colors hover:bg-track-deep disabled:opacity-50"
            >
              采纳调整
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void decide("reject")}
              className="rounded-lg border border-asphalt/30 px-3.5 py-2 text-sm font-medium text-asphalt transition-colors hover:bg-fog disabled:opacity-50"
            >
              保持原计划
            </button>
          </div>
        </div>
      ) : (
        <p className="mt-3 text-sm text-mist">
          {week.some((cell) => cell.session)
            ? "课表没有待确认的调整。"
            : "本周没有安排课次。"}
        </p>
      )}
    </section>
  );
}
