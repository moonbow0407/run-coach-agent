"use client";

/**
 * Scenario Lab 面板：虚拟时钟条 + 记课表单 + 一键场景。
 * 仅当后端开启 lab（GET /dev/clock 可用）时渲染；生产前端永远看不到它。
 * 时间推进后由 controller 回调触发训练台整体重取，课表窗口 / 倒计时 / 状态随之切换。
 */

import { useState } from "react";

import type { DevClockController } from "@/hooks/useDevClock";
import { HARD_FEEDBACK_INPUT, virtualTodayISO } from "@/lib/devClock";
import { formatDateTime, SESSION_NAME } from "@/lib/format";
import type { SessionType } from "@/lib/types";

// 前端固定清单：与后端 SCENARIOS 注册表同名。
const SCENARIO_OPTIONS: ReadonlyArray<{ name: string; label: string }> = [
  { name: "fresh", label: "恢复良好" },
  { name: "fatigue_spike", label: "疲劳激增" },
  { name: "missed_week", label: "中断一周" },
  { name: "race_taper", label: "赛前减量" },
];

const WORKOUT_TYPE_OPTIONS: ReadonlyArray<SessionType> = [
  "easy",
  "tempo",
  "interval",
  "long_run",
  "race",
  "other",
];

const inputClass =
  "rounded-md border border-hairline bg-paper px-2 py-1 font-mono text-xs text-asphalt";

export function ScenarioBar({
  controller,
  latestWorkoutId,
}: {
  controller: DevClockController;
  latestWorkoutId: string | null;
}) {
  const { clock, available, busy, error } = controller;
  // 探测中 / lab 未开启：完全不渲染，正常用户零感知。
  if (available !== true || clock === null) return null;

  const today = virtualTodayISO(clock.virtual_now);
  // 虚拟时钟与墙钟的日历日偏移，给演示者一个直观的「我们跳了几天」。
  const offsetDays = Math.round(
    (new Date(clock.virtual_now).getTime() - new Date(clock.wall_now).getTime()) / 86_400_000,
  );

  return (
    <div className="border-b border-hairline bg-fog">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-5 py-2">
        <span className="font-mono text-[11px] font-semibold uppercase tracking-[0.12em] text-track-deep">
          Scenario Lab
        </span>
        <span className="text-sm font-medium text-asphalt">
          业务今天 <span className="font-mono">{today}</span>
        </span>
        <span className="font-mono text-[11px] text-mist">
          {offsetDays === 0
            ? "与墙钟对齐"
            : `墙钟 ${formatDateTime(clock.wall_now)} · 虚拟 ${offsetDays >= 0 ? "+" : ""}${offsetDays} 天`}
        </span>
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          <QuickButton label="+1小时" disabled={busy} onClick={() => void controller.advance({ plus_hours: 1 })} />
          <QuickButton label="+1天" disabled={busy} onClick={() => void controller.advance({ plus_days: 1 })} />
          <QuickButton label="+7天" disabled={busy} onClick={() => void controller.advance({ plus_days: 7 })} />
          <DateJump busy={busy} onJump={(to) => void controller.advance({ to })} />
          <QuickButton
            label="对齐墙钟"
            disabled={busy}
            onClick={() => void controller.advance({ reset_to_wall: true })}
          />
        </div>
      </div>

      <details className="border-t border-hairline/60">
        <summary className="cursor-pointer select-none px-5 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-mist hover:text-asphalt">
          补数据 · 一键场景
        </summary>
        <div className="flex flex-wrap items-start gap-x-8 gap-y-3 px-5 pb-3">
          <RecordWorkoutForm busy={busy} onSubmit={(input) => void controller.recordWorkout(input)} />
          <div>
            <p className="mb-1.5 font-mono text-[10px] uppercase tracking-wider text-mist">
              一键场景（清空当前用户数据后重种）
            </p>
            <div className="flex flex-wrap gap-1.5">
              {SCENARIO_OPTIONS.map((scenario) => (
                <QuickButton
                  key={scenario.name}
                  label={scenario.label}
                  disabled={busy}
                  onClick={() => {
                    if (window.confirm(`应用「${scenario.label}」会清空当前用户的训练与对话数据，继续？`)) {
                      void controller.applyScenario(scenario.name);
                    }
                  }}
                />
              ))}
            </div>
          </div>
          <div>
            <p className="mb-1.5 font-mono text-[10px] uppercase tracking-wider text-mist">
              快捷反馈（最近一次训练）
            </p>
            <QuickButton
              label="高强度反馈 RPE9"
              disabled={busy || latestWorkoutId === null}
              onClick={() => latestWorkoutId && void controller.giveHardFeedback(latestWorkoutId)}
            />
          </div>
        </div>
        {error ? <p className="px-5 pb-3 text-xs text-track-deep">{error}</p> : null}
      </details>
    </div>
  );
}

function QuickButton({
  label,
  disabled,
  onClick,
}: {
  label: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="rounded-md border border-hairline bg-paper px-2 py-1 font-mono text-xs text-asphalt transition-colors hover:bg-fog disabled:opacity-50"
    >
      {label}
    </button>
  );
}

/** 日期跳转：把业务时间设定到所选日期的上海时间 08:00（只允许前进）。 */
function DateJump({ busy, onJump }: { busy: boolean; onJump: (to: string) => void }) {
  const [picked, setPicked] = useState("");
  return (
    <span className="flex items-center gap-1.5">
      <input
        type="date"
        value={picked}
        onChange={(event) => setPicked(event.target.value)}
        className={inputClass}
        aria-label="跳转日期"
      />
      <QuickButton
        label="跳到该日"
        disabled={busy || picked === ""}
        onClick={() => onJump(`${picked}T08:00:00+08:00`)}
      />
    </span>
  );
}

/** 补录一堂训练：类型 / 距离 / 时长 / 相对业务今天的偏移，可勾选顺带提交高强度反馈。 */
function RecordWorkoutForm({
  busy,
  onSubmit,
}: {
  busy: boolean;
  onSubmit: (input: {
    workout_type: string;
    distance_m: number;
    duration_s: number;
    day_offset: number;
    perceived_exertion?: number;
    subjective_fatigue?: number;
    soreness?: number;
    note?: string;
  }) => void;
}) {
  const [workoutType, setWorkoutType] = useState<SessionType>("easy");
  const [distanceKm, setDistanceKm] = useState("8");
  const [durationMin, setDurationMin] = useState("40");
  const [dayOffset, setDayOffset] = useState("0");
  const [hardFeedback, setHardFeedback] = useState(false);

  const submit = () => {
    const distanceM = Number(distanceKm) * 1000;
    const durationS = Number(durationMin) * 60;
    if (!Number.isFinite(distanceM) || distanceM <= 0 || !Number.isFinite(durationS) || durationS <= 0) {
      return;
    }
    onSubmit({
      workout_type: workoutType,
      distance_m: distanceM,
      duration_s: durationS,
      day_offset: Number(dayOffset),
      ...(hardFeedback ? HARD_FEEDBACK_INPUT : {}),
    });
  };

  return (
    <div>
      <p className="mb-1.5 font-mono text-[10px] uppercase tracking-wider text-mist">记一堂课</p>
      <div className="flex flex-wrap items-center gap-1.5">
        <select
          value={workoutType}
          onChange={(event) => setWorkoutType(event.target.value as SessionType)}
          className={inputClass}
          aria-label="课种"
        >
          {WORKOUT_TYPE_OPTIONS.map((type) => (
            <option key={type} value={type}>
              {SESSION_NAME[type]}
            </option>
          ))}
        </select>
        <input
          type="number"
          min="0.1"
          step="0.5"
          value={distanceKm}
          onChange={(event) => setDistanceKm(event.target.value)}
          className={`${inputClass} w-20`}
          aria-label="距离（公里）"
        />
        <span className="font-mono text-[11px] text-mist">km</span>
        <input
          type="number"
          min="1"
          value={durationMin}
          onChange={(event) => setDurationMin(event.target.value)}
          className={`${inputClass} w-16`}
          aria-label="时长（分钟）"
        />
        <span className="font-mono text-[11px] text-mist">min</span>
        <select
          value={dayOffset}
          onChange={(event) => setDayOffset(event.target.value)}
          className={inputClass}
          aria-label="哪天"
        >
          <option value="0">今天</option>
          <option value="-1">昨天</option>
          <option value="-2">前天</option>
        </select>
        <label className="flex items-center gap-1 font-mono text-[11px] text-mist">
          <input
            type="checkbox"
            checked={hardFeedback}
            onChange={(event) => setHardFeedback(event.target.checked)}
          />
          高强度反馈 RPE9
        </label>
        <QuickButton label="记录" disabled={busy} onClick={submit} />
      </div>
    </div>
  );
}
