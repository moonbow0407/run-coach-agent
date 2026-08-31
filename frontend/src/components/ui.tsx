"use client";

/** 训练台共用的小组件：mono 眉标、指标格、空状态与错误提示。 */

import type { ReactNode } from "react";

/** 眉标：等宽大写小字 + 宽字距，训练日志的记录感。 */
export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <p className="font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-mist">
      {children}
    </p>
  );
}

/** 单个指标：标签在上，值在下。值可用自定义元素（如带单位的组合）。 */
export function Metric({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: ReactNode;
  tone?: "default" | "warn";
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-mist">
        {label}
      </span>
      <span
        className={`text-sm font-medium ${tone === "warn" ? "text-track" : "text-asphalt"}`}
      >
        {value}
      </span>
    </div>
  );
}

export function EmptyState({
  title,
  hint,
}: {
  title: string;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-dashed border-hairline px-4 py-5">
      <p className="text-sm font-medium text-asphalt">{title}</p>
      {hint ? <p className="mt-1 text-sm leading-relaxed text-mist">{hint}</p> : null}
    </div>
  );
}

export function ErrorNote({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-track/40 bg-track-wash px-4 py-3">
      <p className="text-sm text-track-deep">{message}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 font-mono text-xs font-medium uppercase tracking-wider text-track-deep underline underline-offset-4"
        >
          重试
        </button>
      ) : null}
    </div>
  );
}
