/** 训练台的数据展示格式化：距离、时长、目标成绩、日期与课型缩写。 */

import type { SessionType } from "@/lib/types";

export function formatDistance(meters: number | null): string {
  if (meters === null) return "—";
  const km = meters / 1000;
  return `${km % 1 === 0 ? km.toFixed(0) : km.toFixed(1)} km`;
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  // 将秒按四舍五入折算为总分钟，确保满 60 分钟正确进位到小时
  const totalMinutes = Math.round(seconds / 60);
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  if (h === 0) return `${m} min`;
  return `${h}:${String(m).padStart(2, "0")} h`;
}

/** 目标成绩：秒 → 1:50:00 / 45:30。 */
export function formatTargetTime(seconds: number | null): string {
  if (seconds === null) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h === 0) return `${m}:${String(s).padStart(2, "0")}`;
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/** 比赛距离：全马 / 半马用惯称，其余按公里。 */
export function formatRaceDistance(meters: number | null): string | null {
  if (meters === null) return null;
  if (meters === 42195) return "全程马拉松";
  if (meters === 21097) return "半程马拉松";
  return `${(meters / 1000).toFixed(meters % 1000 === 0 ? 0 : 1)} 公里`;
}

/** YYYY-MM-DD → 本地时区的 Date（避免 new Date(string) 按 UTC 解析的偏移）。 */
export function parseDate(dateStr: string): Date {
  const [y, m, d] = dateStr.slice(0, 10).split("-").map(Number);
  return new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1);
}

const pad2 = (n: number) => String(n).padStart(2, "0");

/** Date → YYYY-MM-DD（本地时区），parseDate 的逆变换。 */
export function formatDateISO(date: Date): string {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

export function formatDayMonth(dateStr: string): string {
  const date = parseDate(dateStr);
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

/** ISO 时刻 → 「月-日」，只取日期部分（训练列表行用）。 */
export function formatShortDate(iso: string): string {
  const date = new Date(iso);
  return `${date.getMonth() + 1}-${pad2(date.getDate())}`;
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  return `${date.getMonth() + 1}-${pad2(date.getDate())} ${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
}

/** 距比赛日天数（按本地日历日差，比赛日当天为 0）；today 传 YYYY-MM-DD 时以它为基准。 */
export function daysUntil(dateStr: string, today?: string): number {
  // Scenario Lab 下传入虚拟"业务今天"，使倒计时与 Agent 视角一致；默认本地今天。
  const base = today ? parseDate(today) : new Date();
  base.setHours(0, 0, 0, 0);
  const target = parseDate(dateStr);
  return Math.round((target.getTime() - base.getTime()) / 86_400_000);
}

/** 课型的单字 / 短缩写：课表条上的 mono 标注。 */
export const SESSION_LABEL: Record<SessionType, string> = {
  easy: "E",
  tempo: "T",
  interval: "I",
  long_run: "LR",
  rest: "REST",
  race: "RACE",
  other: "O",
};

/** 课型中文名。 */
export const SESSION_NAME: Record<SessionType, string> = {
  easy: "轻松跑",
  tempo: "节奏跑",
  interval: "间歇跑",
  long_run: "长距离",
  rest: "休息",
  race: "比赛",
  other: "其他",
};

/** 课型的负荷等级（0–1）：决定课表条上柱子的高度，非精确计算值。 */
export const SESSION_LOAD: Record<SessionType, number> = {
  rest: 0.05,
  easy: 0.3,
  other: 0.42,
  tempo: 0.62,
  long_run: 0.78,
  interval: 0.88,
  race: 1,
};

export function formatLoad(load: number | null): string {
  if (load === null) return "—";
  return Math.round(load).toLocaleString("en-US");
}

export function formatPercent(rate: number | null): string {
  if (rate === null) return "—";
  return `${Math.round(rate * 100)}%`;
}

/** 计划调整类型的中文标签。 */
export const CHANGE_TYPE_LABEL: Record<
  "reduce_upcoming_load" | "convert_hard_sessions_to_easy",
  string
> = {
  reduce_upcoming_load: "减负荷",
  convert_hard_sessions_to_easy: "改轻松",
};

/** 处方摘录：距离 / 配速等关键字段拼成一行。 */
export function formatPrescription(prescription: Record<string, unknown>): string {
  const parts: string[] = [];
  const distanceM = prescription["distance_m"];
  if (typeof distanceM === "number") parts.push(formatDistance(distanceM));
  const distanceKm = prescription["distance_km"];
  if (typeof distanceKm === "number") {
    parts.push(`${distanceKm % 1 === 0 ? distanceKm.toFixed(0) : distanceKm.toFixed(1)} km`);
  }
  const duration = prescription["duration_s"];
  if (typeof duration === "number") parts.push(formatDuration(duration));
  const pace = prescription["pace"];
  if (typeof pace === "string") parts.push(`配速 ${pace}`);
  const intent = prescription["intent"];
  if (typeof intent === "string" && parts.length === 0) parts.push(intent);
  return parts.join(" · ");
}
