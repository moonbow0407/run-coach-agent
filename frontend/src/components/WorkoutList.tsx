"use client";

/**
 * 最近训练列表：行内是客观事实（日期 / 距离 / 时长），
 * 展开后懒加载用户报告的主观反馈（RPE / 疲劳 / 酸痛 / 备注）——
 * 客观与主观两类数据在界面上保持清晰分离。
 */

import { useState } from "react";

import { ApiError, apiGet } from "@/lib/api";
import {
  SESSION_NAME,
  formatDateTime,
  formatDistance,
  formatDuration,
} from "@/lib/format";
import type { Workout, WorkoutFeedback } from "@/lib/types";
import { EmptyState, Eyebrow } from "@/components/ui";

const RPE_STEPS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];

function RpeScale({ label, value }: { label: string; value: number | null }) {
  return (
    <div>
      <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-mist">{label}</p>
      <div className="mt-1 flex gap-[3px]" aria-label={`${label} ${value ?? "未报告"} / 10`}>
        {RPE_STEPS.map((step) => (
          <span
            key={step}
            className={`h-2.5 w-2 rounded-sm ${
              value !== null && step <= value ? "bg-asphalt" : "bg-hairline"
            }`}
          />
        ))}
      </div>
    </div>
  );
}

function WorkoutRow({ workout }: { workout: Workout }) {
  const [feedback, setFeedback] = useState<WorkoutFeedback | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && feedback === null && error === null) {
      try {
        setFeedback(
          await apiGet<WorkoutFeedback>(`/api/v1/workouts/${workout.id}/feedback`),
        );
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          setFeedback(null); // 没写过反馈：展开区显示提示。
        } else {
          setError(err instanceof Error ? err.message : "无法读取反馈");
        }
      }
    }
  };

  return (
    <div className="border-b border-hairline last:border-b-0">
      <button
        type="button"
        onClick={() => void toggle()}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-1 py-2.5 text-left transition-colors hover:bg-fog"
      >
        <div className="flex min-w-0 items-baseline gap-3">
          <span className="font-mono text-xs text-mist">{formatDateTime(workout.started_at).split(" ")[0]}</span>
          <span className="truncate text-sm font-medium text-asphalt">
            {SESSION_NAME[workout.workout_type]}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-3 font-mono text-xs text-mist">
          <span>{formatDistance(workout.distance_m)}</span>
          <span>{formatDuration(workout.duration_s)}</span>
          <span aria-hidden className={`transition-transform ${open ? "rotate-90" : ""}`}>
            ▸
          </span>
        </div>
      </button>

      {open ? (
        <div className="px-1 pb-3.5">
          {error ? (
            <p className="text-sm text-track-deep">{error}</p>
          ) : feedback ? (
            <div className="space-y-3 rounded-lg bg-fog p-3">
              <div className="grid grid-cols-3 gap-3">
                <RpeScale label="用力程度 RPE" value={feedback.perceived_exertion} />
                <RpeScale label="主观疲劳" value={feedback.subjective_fatigue} />
                <RpeScale label="酸痛" value={feedback.soreness} />
              </div>
              {feedback.note ? (
                <p className="text-sm leading-relaxed text-asphalt">「{feedback.note}」</p>
              ) : null}
            </div>
          ) : (
            <p className="text-sm text-mist">这次训练还没有主观反馈。</p>
          )}
        </div>
      ) : null}
    </div>
  );
}

export function WorkoutList({ workouts }: { workouts: Workout[] | null }) {
  return (
    <section className="rounded-xl border border-hairline bg-paper p-4">
      <Eyebrow>最近 30 天训练</Eyebrow>
      <div className="mt-2">
        {workouts === null ? (
          <EmptyState title="教练还没有评估过你的状态" />
        ) : workouts.length === 0 ? (
          <EmptyState
            title="最近 30 天没有训练记录"
            hint="记录一次训练后，教练就能结合实际表现给你建议。"
          />
        ) : (
          <div className="divide-y divide-hairline">
            {workouts.map((workout) => (
              <WorkoutRow key={workout.id} workout={workout} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
