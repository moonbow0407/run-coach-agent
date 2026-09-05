"use client";

/**
 * 最近训练列表：行内是客观事实（日期 / 距离 / 时长），
 * 展开后懒加载用户报告的主观反馈（RPE / 疲劳 / 酸痛 / 备注）——
 * 客观与主观两类数据在界面上保持清晰分离。
 */

import { memo, useState } from "react";

import { ApiError, apiGet, apiPost } from "@/lib/api";
import {
  SESSION_NAME,
  formatDistance,
  formatDuration,
  formatShortDate,
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

function ScaleSelector({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (val: number) => void;
}) {
  return (
    <div>
      <div className="flex items-center justify-between">
        <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-mist">{label}</p>
        <span className="font-mono text-xs font-semibold text-asphalt">{value} / 10</span>
      </div>
      <div className="mt-1 flex gap-1">
        {RPE_STEPS.map((step) => (
          <button
            key={step}
            type="button"
            onClick={() => onChange(step)}
            className={`flex-1 rounded py-1 text-center font-mono text-xs transition-colors ${
              step === value
                ? "bg-asphalt font-semibold text-paper"
                : "bg-fog text-mist hover:bg-hairline"
            }`}
          >
            {step}
          </button>
        ))}
      </div>
    </div>
  );
}

function FeedbackForm({
  workoutId,
  initialFeedback,
  onSaved,
  onCancel,
}: {
  workoutId: string;
  initialFeedback?: WorkoutFeedback | null;
  onSaved: (feedback: WorkoutFeedback) => void;
  onCancel?: () => void;
}) {
  const [rpe, setRpe] = useState<number>(initialFeedback?.perceived_exertion ?? 5);
  const [fatigue, setFatigue] = useState<number>(initialFeedback?.subjective_fatigue ?? 4);
  const [soreness, setSoreness] = useState<number>(initialFeedback?.soreness ?? 3);
  const [note, setNote] = useState<string>(initialFeedback?.note ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const saved = await apiPost<WorkoutFeedback>(
        `/api/v1/workouts/${workoutId}/feedback`,
        {
          perceived_exertion: rpe,
          subjective_fatigue: fatigue,
          soreness: soreness,
          note: note.trim() || null,
        },
      );
      onSaved(saved);
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存反馈失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3 rounded-lg border border-hairline bg-fog p-3.5">
      <div className="flex items-center justify-between">
        <p className="font-mono text-xs font-semibold uppercase tracking-wider text-asphalt">
          记录主观反馈
        </p>
        {onCancel ? (
          <button
            type="button"
            onClick={onCancel}
            className="font-mono text-xs text-mist hover:text-asphalt"
          >
            取消
          </button>
        ) : null}
      </div>

      <ScaleSelector label="自觉用力程度 (RPE)" value={rpe} onChange={setRpe} />
      <ScaleSelector label="主观疲劳程度" value={fatigue} onChange={setFatigue} />
      <ScaleSelector label="肌肉酸痛程度" value={soreness} onChange={setSoreness} />

      <div>
        <label className="font-mono text-[10px] uppercase tracking-[0.12em] text-mist">
          备注心得（选填）
        </label>
        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="如：最后两公里心率漂移、双腿轻快…"
          className="mt-1 w-full rounded border border-hairline bg-paper px-2.5 py-1.5 text-xs text-asphalt outline-none focus:border-asphalt"
        />
      </div>

      {error ? <p className="text-xs text-track-deep">{error}</p> : null}

      <div className="flex justify-end pt-1">
        <button
          type="submit"
          disabled={saving}
          className="rounded-md bg-asphalt px-3 py-1.5 font-mono text-xs font-medium text-paper transition-colors hover:bg-asphalt/85 disabled:opacity-50"
        >
          {saving ? "保存中…" : "保存反馈"}
        </button>
      </div>
    </form>
  );
}

function WorkoutRow({
  workout,
  onFeedbackSaved,
}: {
  workout: Workout;
  onFeedbackSaved?: (feedback: WorkoutFeedback) => void;
}) {
  const [feedback, setFeedback] = useState<WorkoutFeedback | null>(null);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const fetchFeedback = async () => {
    setError(null);
    setLoading(true);
    try {
      setFeedback(
        await apiGet<WorkoutFeedback>(`/api/v1/workouts/${workout.id}/feedback`),
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setFeedback(null); // 没写过反馈：展开区显示提示与打分按钮。
      } else {
        setError(err instanceof Error ? err.message : "无法读取反馈");
      }
    } finally {
      setLoading(false);
      setLoaded(true);
    }
  };

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && !loaded && !loading) {
      await fetchFeedback();
    }
  };

  const handleSaved = (newFeedback: WorkoutFeedback) => {
    setFeedback(newFeedback);
    setEditing(false);
    onFeedbackSaved?.(newFeedback);
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
          <span className="font-mono text-xs text-mist">{formatShortDate(workout.started_at)}</span>
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
            <div className="flex items-center justify-between gap-2 rounded-lg bg-track-wash px-3 py-2">
              <p className="text-sm text-track-deep">{error}</p>
              <button
                type="button"
                onClick={() => void fetchFeedback()}
                className="font-mono text-xs font-medium text-track-deep underline underline-offset-4"
              >
                重试加载
              </button>
            </div>
          ) : loading || !loaded ? (
            <p className="px-1 py-2 font-mono text-xs text-mist">加载主观反馈…</p>
          ) : editing || feedback === null ? (
            <FeedbackForm
              workoutId={workout.id}
              initialFeedback={feedback}
              onSaved={handleSaved}
              onCancel={feedback ? () => setEditing(false) : undefined}
            />
          ) : feedback ? (
            <div className="space-y-3 rounded-lg bg-fog p-3">
              <div className="flex items-center justify-between">
                <p className="font-mono text-[11px] uppercase tracking-wider text-mist">
                  主观反馈记录
                </p>
                <button
                  type="button"
                  onClick={() => setEditing(true)}
                  className="font-mono text-xs text-mist underline underline-offset-2 hover:text-asphalt"
                >
                  修改
                </button>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <RpeScale label="用力程度 RPE" value={feedback.perceived_exertion} />
                <RpeScale label="主观疲劳" value={feedback.subjective_fatigue} />
                <RpeScale label="酸痛" value={feedback.soreness} />
              </div>
              {feedback.note ? (
                <p className="text-sm leading-relaxed text-asphalt">「{feedback.note}」</p>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

// 对话流式期间父组件高频重渲染：props 不变时跳过整块训练列表的重绘。
export const WorkoutList = memo(function WorkoutList({
  workouts,
  onFeedbackSaved,
}: {
  workouts: Workout[] | null;
  onFeedbackSaved?: (feedback: WorkoutFeedback) => void;
}) {
  return (
    <section className="rounded-xl border border-hairline bg-paper p-4">
      <Eyebrow>最近 30 天训练</Eyebrow>
      <div className="mt-2">
        {workouts === null ? (
          <EmptyState
            title="暂无训练记录"
            hint="记录一次训练后，教练就能结合实际表现给你建议。"
          />
        ) : workouts.length === 0 ? (
          <EmptyState
            title="最近 30 天没有训练记录"
            hint="记录一次训练后，教练就能结合实际表现给你建议。"
          />
        ) : (
          <div className="divide-y divide-hairline">
            {workouts.map((workout) => (
              <WorkoutRow
                key={workout.id}
                workout={workout}
                onFeedbackSaved={onFeedbackSaved}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
});
