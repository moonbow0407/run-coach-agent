"use client";

/**
 * Scenario Lab 虚拟时钟控制器：探测 / 慢速轮询 / 推进，并把变更回调给数据层刷新。
 * 后端未开启 lab（GET /dev/clock 404）时 clock 恒为 null，面板随之隐藏；
 * 所有写操作完成后统一触发 onChanged，由调用方决定重取哪些数据。
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  advanceDevClock,
  applyDevScenario,
  fetchDevClock,
  postHardFeedback,
  recomputeDevState,
  recordDevWorkout,
  type AdvancePayload,
  type DevClock,
  type DevWorkoutInput,
} from "@/lib/devClock";

const POLL_INTERVAL_MS = 5000;

export interface DevClockController {
  clock: DevClock | null; // null = lab 未开启或尚未探测完成
  available: boolean | null; // null = 探测中；true/false 决定面板显隐
  busy: boolean; // 任一 lab 写操作进行中
  error: string | null; // 最近一次操作失败的用户可读文案
  advance(payload: AdvancePayload): Promise<void>;
  applyScenario(name: string): Promise<void>;
  recordWorkout(input: DevWorkoutInput): Promise<void>;
  giveHardFeedback(workoutId: string): Promise<void>;
}

export function useDevClock(onChanged?: () => void): DevClockController {
  const [clock, setClock] = useState<DevClock | null>(null);
  const [available, setAvailable] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 回调走 ref：轮询 effect 不因回调身份变化重启，且始终调用最新闭包。
  const onChangedRef = useRef(onChanged);
  onChangedRef.current = onChanged;

  // 探测 + 慢速轮询：另一标签页或 API 进程推进时间后，本页最迟一个周期对齐。
  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await fetchDevClock();
        if (stopped) return;
        setAvailable(true);
        setClock(next);
      } catch {
        // 探测/轮询失败视为 lab 不可用：lab 是纯演示能力，不打扰正常使用。
        if (!stopped) setAvailable(false);
      } finally {
        if (!stopped) timer = window.setTimeout(poll, POLL_INTERVAL_MS);
      }
    };
    void poll();
    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);

  const run = useCallback(async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      onChangedRef.current?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scenario Lab 操作失败");
    } finally {
      setBusy(false);
    }
  }, []);

  const advance = useCallback(
    (payload: AdvancePayload) =>
      run(async () => {
        setClock(await advanceDevClock(payload));
      }),
    [run],
  );

  const applyScenario = useCallback(
    (name: string) =>
      run(async () => {
        await applyDevScenario(name);
      }),
    [run],
  );

  // 记课后立刻同步重算快照：UI 即时反映新负荷，不必等 Worker 的 5s cron。
  const recordWorkout = useCallback(
    (input: DevWorkoutInput) =>
      run(async () => {
        await recordDevWorkout(input);
        await recomputeDevState();
      }),
    [run],
  );

  const giveHardFeedback = useCallback(
    (workoutId: string) =>
      run(async () => {
        await postHardFeedback(workoutId);
        await recomputeDevState();
      }),
    [run],
  );

  return { clock, available, busy, error, advance, applyScenario, recordWorkout, giveHardFeedback };
}
