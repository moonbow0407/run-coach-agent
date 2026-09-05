"use client";

/**
 * 训练台组合层：页头（目标 + 状态）+ 对话流 + 课表与训练侧栏。
 * 一轮对话结束后刷新「待确认提案」与状态快照；提案落定后刷新课表。
 */

import { useState } from "react";

import { Chat } from "@/components/Chat";
import { DashboardHeader } from "@/components/DashboardHeader";
import { ScenarioBar } from "@/components/ScenarioBar";
import { WeekPlan } from "@/components/WeekPlan";
import { WorkoutList } from "@/components/WorkoutList";
import { ErrorNote } from "@/components/ui";
import { useChat } from "@/hooks/useChat";
import { useDevClock } from "@/hooks/useDevClock";
import { useTrainingData } from "@/hooks/useTrainingData";
import { virtualTodayISO } from "@/lib/devClock";
import { tokenUserId } from "@/lib/token";

type View = "chat" | "desk";

export function TrainingDesk({
  token,
  onUnauthorized,
}: {
  token: string;
  onUnauthorized: () => void;
}) {
  const [view, setView] = useState<View>("chat");
  const data = useTrainingData(true);

  const chat = useChat(true, () => void data.reloadAfterRun(), onUnauthorized);

  // Scenario Lab：后端未开启时面板自动隐藏；任何 lab 变更后整体重取训练台数据。
  const devClock = useDevClock(() => void data.reload());
  // 业务今天：lab 下取虚拟时钟（上海日历日），未开启时 undefined 走前端本地今天。
  const today = devClock.clock ? virtualTodayISO(devClock.clock.virtual_now) : undefined;

  const userId = tokenUserId(token);
  const userIdShort = userId ? `${userId.slice(0, 8)}` : "";

  const desk = (
    <div className="flex flex-col gap-4">
      <WeekPlan
        plan={data.plan}
        pendingChange={data.pendingChange}
        onDecided={data.reloadAfterDecision}
        onRefresh={data.reload}
        today={today}
      />
      <WorkoutList
        workouts={data.workouts?.workouts ?? null}
        onFeedbackSaved={data.reloadAfterRun}
      />
    </div>
  );

  return (
    <div className="flex min-h-screen flex-col">
      {/* 连接信息条 */}
      <div className="border-b border-hairline bg-paper">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-1.5">
          <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-mist">
            ● 已连接 · user {userIdShort}
          </p>
          <button
            type="button"
            onClick={onUnauthorized}
            className="font-mono text-[11px] uppercase tracking-[0.12em] text-mist underline underline-offset-4 hover:text-asphalt"
          >
            断开
          </button>
        </div>
      </div>

      <ScenarioBar
        controller={devClock}
        latestWorkoutId={data.workouts?.workouts?.[0]?.id ?? null}
      />

      <DashboardHeader goal={data.goal} state={data.state} today={today} safety={data.safety} />

      {data.error ? (
        <div className="mx-auto mt-4 w-full max-w-6xl px-5">
          <ErrorNote message={data.error} onRetry={() => void data.reload()} />
        </div>
      ) : null}

      {/* 移动端切换 */}
      <div className="mx-auto mt-3 w-full max-w-6xl px-5 md:hidden">
        <div className="grid grid-cols-2 gap-1 rounded-lg border border-hairline bg-paper p-1">
          {(["chat", "desk"] as const).map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => setView(key)}
              className={`rounded-md px-3 py-1.5 font-mono text-xs uppercase tracking-wider transition-colors ${
                view === key ? "bg-asphalt text-paper" : "text-mist"
              }`}
            >
              {key === "chat" ? "对话" : "课表与训练"}
            </button>
          ))}
        </div>
      </div>

      <main className="mx-auto grid w-full max-w-6xl flex-1 grid-cols-1 gap-4 px-5 py-4 md:grid-cols-[1.6fr_1fr]">
        <div className={`${view === "chat" ? "flex" : "hidden"} min-h-0 flex-col md:flex`}>
          <Chat
            messages={chat.messages}
            run={chat.run}
            historyError={chat.historyError}
            pendingPlanChange={chat.pendingPlanChange}
            planChangeActions={chat.planChangeActions}
            onSend={chat.send}
            onCancel={chat.cancel}
            onNewThread={chat.startNewThread}
            onPlanChangeDecided={() => {
              chat.clearPendingPlanChange();
              void data.reloadAfterDecision();
            }}
          />
        </div>
        <aside className={`${view === "desk" ? "" : "hidden"} md:block`}>{desk}</aside>
      </main>
    </div>
  );
}
