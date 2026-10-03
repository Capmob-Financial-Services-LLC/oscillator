// Response types mirroring the backend Pydantic schemas (app/schemas/insights.py).

export type Range = "day" | "week" | "month" | "all";

export interface Metric {
  current: number | null;
  previous: number | null;
  delta_pct: number | null;
}

export interface Overview {
  range: Range;
  period_start: string;
  period_end: string;
  throughput: Metric;
  avg_cycle_hours: Metric;
  comments: Metric;
  wip: number;
  open_issues: number;
}

export interface TimePoint {
  period: string;
  value: number | null;
}

export interface DualPoint {
  period: string;
  completed: number;
  created: number;
}

export interface ThroughputResp {
  range: Range;
  unit: string;
  series: DualPoint[];
}

export interface CyclePoint {
  period: string;
  avg_hours: number | null;
  median_hours: number | null;
}

export interface CycleTimeResp {
  range: Range;
  unit: string;
  series: CyclePoint[];
}

export interface WipResp {
  range: Range;
  unit: string;
  current: number;
  series: TimePoint[];
}

export interface ActorStat {
  actor_id: number;
  name: string | null;
  email: string | null;
  avatar_url: string | null;
  throughput: number;
  avg_cycle_hours: number | null;
  comments: number;
  created: number;
  sparkline: number[];
}

export interface ByActorResp {
  range: Range;
  period_start: string;
  period_end: string;
  actors: ActorStat[];
}

export interface ActorThroughputPoint {
  period: string;
  completed: number;
  created: number;
}

export interface ActorThroughputStat {
  actor_id: number;
  name: string | null;
  email: string | null;
  series: ActorThroughputPoint[];
}

export interface ThroughputByActorResp {
  range: Range;
  unit: string;
  actors: ActorThroughputStat[];
}

export interface TeamStat {
  team_id: number;
  name: string | null;
  key: string | null;
  throughput: number;
  avg_cycle_hours: number | null;
  median_cycle_hours: number | null;
  wip: number;
  comments: number;
  scope_added: number;
}

export interface ByTeamResp {
  range: Range;
  period_start: string;
  teams: TeamStat[];
}

export interface ActorIssue {
  issue_id: number;
  title: string | null;
  identifier: string | null;
  team_name: string | null;
  completed_at: string | null;
  cycle_hours: number | null;
  labels: string[];
}

export interface ActorIssuesResp {
  actor_id: number;
  name: string | null;
  email: string | null;
  range: Range;
  period_start: string;
  period_end: string;
  issues: ActorIssue[];
}

// ---------------------------------------------------------------------------
// Custom issues — non-Linear work items (e.g. "set up AWS") tracked manually
// but counted in the same tallies as synced Linear issues.
// ---------------------------------------------------------------------------

export interface ActorDropdown {
  actor_id: number;
  name: string | null;
  email: string | null;
  avatar_url: string | null;
}

export type CustomIssueStatus = "unstarted" | "started" | "completed" | "canceled";

export interface CustomIssue {
  id: number;
  identifier: string | null;
  title: string | null;
  assignee_id: number | null;
  assignee_name: string | null;
  assignee_email: string | null;
  status: CustomIssueStatus;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  canceled_at: string | null;
}

export interface CustomIssueListResp {
  issues: CustomIssue[];
  total: number;
}

// ---------------------------------------------------------------------------
// Engineering Points — the Linear label-driven scoring ledger.
// Mirrors backend/app/schemas/points.py.
// ---------------------------------------------------------------------------

export interface PointsCategoryBreakdown {
  category: string;
  points: number;
}

export interface PointsActorStat {
  actor_id: number;
  name: string | null;
  email: string | null;
  avatar_url: string | null;
  total_points: number;
  by_category: PointsCategoryBreakdown[];
}

export interface PointsByActorResp {
  range: Range;
  period_start: string;
  period_end: string;
  actors: PointsActorStat[];
}

export interface PointsLedgerEntry {
  id: number;
  issue_id: number;
  identifier: string | null;
  title: string | null;
  actor_id: number | null;
  name: string | null;
  category: string;
  event_kind: "award" | "reversal" | "bonus";
  points: number;
  rule_key: string | null;
  label_state: string[] | Record<string, unknown> | null;
  effective_at: string;
  awarded_at: string;
  reverses_event_id: number | null;
  related_event_id: number | null;
}

export interface PointsLedgerResp {
  entries: PointsLedgerEntry[];
  total: number;
}

export interface UnscoredTicketItem {
  issue_id: number;
  identifier: string | null;
  title: string | null;
  assignee_id: number | null;
  assignee_name: string | null;
  reason: string;
  first_detected_at: string;
  last_checked_at: string;
  notified_at: string | null;
  team: string | null;
}

export interface UnscoredResp {
  range: Range;
  tickets: UnscoredTicketItem[];
}


// ---- Delivery: was dated work finished by its Target date -------------------

export interface DeliveryStat {
  actor_id: number | null;
  name: string;
  avatar_url: string | null;
  on_time: number;
  late: number;
  overdue: number;
  due_soon: number;
  avg_days_late: number | null;
  /** 100 x on_time / (on_time + late + overdue); null when nothing was due. */
  score: number | null;
}

export interface DatedIssue {
  identifier: string | null;
  title: string | null;
  team: string | null;
  assignee: string | null;
  target_date: string;
  /** Days past the date (overdue) or until it (due soon). */
  days: number;
  url: string | null;
}

export interface DeliveryResp {
  since: string;
  today: string;
  totals: DeliveryStat;
  by_actor: DeliveryStat[];
  overdue: DatedIssue[];
  due_soon: DatedIssue[];
}
