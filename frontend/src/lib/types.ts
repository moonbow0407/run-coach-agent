/** 后端 HTTP API 的响应类型，字段口径与 backend/app/api/schemas 一致。 */

export type SessionType =
  | "easy"
  | "tempo"
  | "interval"
  | "long_run"
  | "rest"
  | "race"
  | "other";

export interface ActiveGoal {
  id: string;
  goal_type: "race" | "general";
  race_date: string | null; // YYYY-MM-DD
  race_distance_m: number | null;
  target_time_s: number | null;
  status: "active" | "completed" | "cancelled";
  created_at: string;
  updated_at: string;
}

export interface PlanSummary {
  id: string;
  version: number;
  status: string;
  starts_on: string;
  ends_on: string;
  goal_id: string | null;
}

export interface PlannedSession {
  id: string;
  scheduled_date: string; // YYYY-MM-DD
  session_type: SessionType;
  title: string;
  prescription: Record<string, unknown>;
}

export interface ActivePlan {
  plan: PlanSummary;
  window_start: string;
  window_end: string;
  truncated: boolean;
  sessions: PlannedSession[];
}

export interface AthleteStateSignal {
  code: string;
  severity: string;
  message: string;
  evidence_refs: string[];
}

export interface AthleteState {
  id: string;
  version: number;
  as_of: string;
  fatigue_level: "low" | "moderate" | "high" | null;
  recovery_level: "poor" | "fair" | "good" | null;
  recent_training_load: number | null;
  workout_completion_rate: number | null;
  training_load_coverage: number | null;
  signals: AthleteStateSignal[];
  confidence: number | null;
  algorithm_version: string;
  created_at: string;
}

export interface Workout {
  id: string;
  started_at: string;
  distance_m: number | null;
  duration_s: number | null;
  avg_heart_rate: number | null;
  max_heart_rate: number | null;
  workout_type: SessionType;
  source: "seed" | "manual";
  created_at: string;
}

export interface WorkoutList {
  count: number;
  workouts: Workout[];
}

export interface WorkoutFeedback {
  id: string;
  user_id: string;
  workout_id: string;
  perceived_exertion: number | null;
  subjective_fatigue: number | null;
  soreness: number | null;
  note: string | null;
  created_at: string;
}

export interface SessionChange {
  source_session_id: string;
  scheduled_date: string;
  from_type: SessionType;
  to_type: SessionType;
  old_title: string;
  new_title: string;
  old_prescription: Record<string, unknown>;
  new_prescription: Record<string, unknown>;
}

export interface PlanChange {
  id: string;
  user_id: string;
  from_plan_id: string;
  from_plan_version: number;
  based_on_state_id: string;
  based_on_state_version: number;
  source_turn_id: string | null;
  source_run_id: string | null;
  as_of: string;
  change_type: "reduce_upcoming_load";
  payload: {
    horizon_days: number;
    changes: SessionChange[];
  };
  reason: string;
  status:
    | "draft"
    | "pending_confirmation"
    | "confirmed"
    | "rejected"
    | "stale"
    | "abandoned";
  created_at: string;
  resolved_at: string | null;
  resulting_plan_id: string | null;
}

export interface ResultingPlan {
  id: string;
  version: number;
  status: string;
  starts_on: string;
  ends_on: string;
  goal_id: string | null;
  sessions: PlannedSession[];
}

export interface ConfirmPlanChangeResult {
  plan_change: PlanChange;
  resulting_plan_id: string | null;
  resulting_plan: ResultingPlan | null;
}

export interface ThreadMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}
