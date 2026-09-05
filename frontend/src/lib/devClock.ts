/** Scenario Lab 客户端：虚拟时钟读写、补录训练、同步重算与一键场景。 */

import { apiGet, apiPost, ApiError } from "@/lib/api";

export interface DevClock {
  virtual_now: string; // 业务"现在"（lab 时钟，ISO UTC）
  wall_now: string; // 真实墙上时钟，用于展示偏移
}

export interface AdvancePayload {
  to?: string; // 直接设定到某时刻（ISO，必须不早于当前虚拟时间）
  plus_days?: number; // 向前推的天数
  plus_hours?: number; // 向前推的小时数
  reset_to_wall?: boolean; // 清除虚拟时刻，回到墙上时钟
}

export interface DevWorkoutInput {
  workout_type: string;
  distance_m?: number;
  duration_s?: number;
  avg_heart_rate?: number;
  max_heart_rate?: number;
  day_offset?: number; // 相对业务今天：-1=昨天，0=今天
  perceived_exertion?: number; // 内联反馈：用力程度 RPE（1–10）
  subjective_fatigue?: number; // 内联反馈：主观疲劳
  soreness?: number; // 内联反馈：酸痛
  note?: string; // 内联反馈：自由备注
}

interface DevWorkoutRecord {
  id: string;
  started_at: string;
  workout_type: string;
  feedback_id: string | null; // 顺带写入的反馈 ID；未提交反馈为空
  recompute_version: number; // 后端同步重算后的快照版本
}

interface DevRecomputeResult {
  as_of: string;
  version: number;
  appended: boolean;
}

/** 读取 lab 时钟；后端未开启 lab（404）时返回 null，前端据此隐藏面板。 */
export async function fetchDevClock(): Promise<DevClock | null> {
  try {
    return await apiGet<DevClock>("/api/v1/dev/clock");
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export function advanceDevClock(payload: AdvancePayload): Promise<DevClock> {
  return apiPost<DevClock>("/api/v1/dev/clock", payload);
}

export function recordDevWorkout(input: DevWorkoutInput): Promise<DevWorkoutRecord> {
  return apiPost<DevWorkoutRecord>("/api/v1/dev/workouts", input);
}

/** 以业务"现在"同步重算状态快照：演示时立刻看到新状态，不等 Worker 投影。 */
export function recomputeDevState(): Promise<DevRecomputeResult> {
  return apiPost<DevRecomputeResult>("/api/v1/dev/athlete-state/recompute");
}

/** 一键高强度反馈（对齐 seed 话术）：RPE9 / 疲劳9 / 酸痛8。 */
export const HARD_FEEDBACK_INPUT = {
  perceived_exertion: 9,
  subjective_fatigue: 9,
  soreness: 8,
  note: "最后两组间歇明显掉速，今天腿很酸",
} as const;

export function postHardFeedback(workoutId: string): Promise<unknown> {
  return apiPost(`/api/v1/workouts/${workoutId}/feedback`, HARD_FEEDBACK_INPUT);
}

export function applyDevScenario(
  name: string,
): Promise<{ scenario: string; workout_count: number }> {
  return apiPost(`/api/v1/dev/scenarios/${name}/apply`);
}

/** 业务"今天"（上海日历日）→ YYYY-MM-DD；与 race_date / 课表日期同口径比较。 */
export function virtualTodayISO(virtualNow: string): string {
  // sv-SE locale 恰好输出 YYYY-MM-DD 格式。
  return new Date(virtualNow).toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" });
}
