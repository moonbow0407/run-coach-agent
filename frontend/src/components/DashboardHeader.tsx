"use client";

/**
 * 训练台页头：上半是目标（比赛倒计时大数字），下半是系统推导的
 * 跑者状态快照。快照的 as_of / 置信度 / 评估版本全部展示——
 * 「系统认为你现在怎么样」必须可解释、可追溯，这是本产品的立场。
 */

import { Eyebrow, Metric } from "@/components/ui";
import {
  daysUntil,
  formatDateTime,
  formatLoad,
  formatPercent,
  formatRaceDistance,
  formatTargetTime,
} from "@/lib/format";
import type { ActiveGoal, AthleteState } from "@/lib/types";

const FATIGUE_LABEL = { low: "低", moderate: "中", high: "高" } as const;
const RECOVERY_LABEL = { poor: "差", fair: "一般", good: "好" } as const;

export function DashboardHeader({
  goal,
  state,
}: {
  goal: ActiveGoal | null;
  state: AthleteState | null;
}) {
  const raceName = formatRaceDistance(goal?.race_distance_m ?? null);
  const countdown = goal?.race_date ? daysUntil(goal.race_date) : null;

  return (
    <header className="border-b border-hairline">
      <div className="mx-auto flex max-w-6xl flex-wrap items-end justify-between gap-x-8 gap-y-4 px-5 pt-5 pb-4">
        <div>
          <Eyebrow>训练台 · Training Desk</Eyebrow>
          {goal && goal.goal_type === "race" ? (
            <p className="mt-1.5 text-lg font-semibold tracking-tight">
              {raceName ?? "比赛目标"}
              <span className="mx-2 text-hairline">|</span>
              <span className="font-mono text-base font-medium">
                {formatTargetTime(goal.target_time_s)}
              </span>
            </p>
          ) : goal ? (
            <p className="mt-1.5 text-lg font-semibold tracking-tight">日常训练目标</p>
          ) : (
            <p className="mt-1.5 text-lg font-semibold tracking-tight text-mist">
              还没有训练目标
            </p>
          )}
        </div>

        {countdown !== null && countdown >= 0 ? (
          <div className="flex items-end gap-2">
            <span className="font-mono text-5xl leading-none font-semibold [font-stretch:75%] text-asphalt">
              {countdown}
            </span>
            <span className="pb-0.5 text-sm text-mist">
              {countdown === 0 ? "今天比赛" : "天后比赛"}
            </span>
          </div>
        ) : null}
      </div>

      <div className="mx-auto max-w-6xl px-5 pb-4">
        {state ? (
          <div className="flex flex-wrap items-start gap-x-8 gap-y-3">
            <Metric
              label="疲劳"
              value={state.fatigue_level ? FATIGUE_LABEL[state.fatigue_level] : "—"}
              tone={state.fatigue_level === "high" ? "warn" : "default"}
            />
            <Metric
              label="恢复"
              value={state.recovery_level ? RECOVERY_LABEL[state.recovery_level] : "—"}
            />
            <Metric label="周负荷" value={formatLoad(state.recent_training_load)} />
            <Metric label="完成率" value={formatPercent(state.workout_completion_rate)} />
            <Metric
              label="证据截至"
              value={<span className="font-mono">{formatDateTime(state.as_of)}</span>}
            />
            <Metric label="评估版本" value={<span className="font-mono">{state.algorithm_version}</span>} />
            {state.signals.length > 0 ? (
              <p className="w-full text-sm leading-relaxed text-mist">
                依据：{state.signals.map((signal) => signal.message).join("；")}
              </p>
            ) : null}
          </div>
        ) : (
          <p className="pb-1 text-sm text-mist">
            教练还没有评估过你的状态——提交一次训练反馈后就会生成。
          </p>
        )}
      </div>
    </header>
  );
}
