"use client";

/** 训练台数据源：目标 / 计划 / 状态 / 训练 / 待确认提案的一次性装载与局部刷新。 */

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiGet } from "@/lib/api";
import type { ActiveGoal, ActivePlan, AthleteState, PlanChange, WorkoutList } from "@/lib/types";

/** 404 表示「还没有这类数据」，按空状态处理而不是错误。 */
async function getOrNull<T>(path: string): Promise<T | null> {
  try {
    return await apiGet<T>(path);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export interface TrainingData {
  goal: ActiveGoal | null;
  plan: ActivePlan | null;
  state: AthleteState | null;
  workouts: WorkoutList | null;
  pendingChange: PlanChange | null;
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
  /** 一轮对话结束后：提案可能刚生成，状态可能已被评估刷新。 */
  reloadAfterRun: () => Promise<void>;
  /** 提案落定（采纳 / 保持）后：课表换版本、pending 清空。 */
  reloadAfterDecision: () => Promise<void>;
}

export function useTrainingData(enabled: boolean): TrainingData {
  const [goal, setGoal] = useState<ActiveGoal | null>(null);
  const [plan, setPlan] = useState<ActivePlan | null>(null);
  const [state, setState] = useState<AthleteState | null>(null);
  const [workouts, setWorkouts] = useState<WorkoutList | null>(null);
  const [pendingChange, setPendingChange] = useState<PlanChange | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [goalData, planData, stateData, workoutData, pendingData] = await Promise.all([
        getOrNull<ActiveGoal>("/api/v1/goals/active"),
        getOrNull<ActivePlan>("/api/v1/plans/active"),
        getOrNull<AthleteState>("/api/v1/athlete-state/latest"),
        getOrNull<WorkoutList>("/api/v1/workouts?days=30"),
        getOrNull<PlanChange>("/api/v1/plan-changes/pending"),
      ]);
      setGoal(goalData);
      setPlan(planData);
      setState(stateData);
      setWorkouts(workoutData);
      setPendingChange(pendingData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法加载训练数据");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (enabled) void load();
  }, [enabled, load]);

  const reloadAfterRun = useCallback(async () => {
    try {
      const [stateData, pendingData] = await Promise.all([
        getOrNull<AthleteState>("/api/v1/athlete-state/latest"),
        getOrNull<PlanChange>("/api/v1/plan-changes/pending"),
      ]);
      setState(stateData);
      setPendingChange(pendingData);
    } catch {
      // 局部刷新失败不打断对话；下次整页重载会补上。
    }
  }, []);

  const reloadAfterDecision = useCallback(async () => {
    try {
      const [planData, pendingData] = await Promise.all([
        getOrNull<ActivePlan>("/api/v1/plans/active"),
        getOrNull<PlanChange>("/api/v1/plan-changes/pending"),
      ]);
      setPlan(planData);
      setPendingChange(pendingData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法刷新课表");
    }
  }, []);

  return {
    goal,
    plan,
    state,
    workouts,
    pendingChange,
    loading,
    error,
    reload: load,
    reloadAfterRun,
    reloadAfterDecision,
  };
}
