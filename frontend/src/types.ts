export type Result = "green" | "yellow" | "red" | "skipped";

export interface Assignment {
  id: string;
  problem_id: number;
  leetcode_id: number;
  slug: string;
  title: string;
  url?: string;
  difficulty?: string;
  pattern_id?: string;
  pattern_title?: string;
  pattern_description?: string;
  recognition_signals: string[];
  assigned_on: string;
  date_label: string;
  mode: string;
  status: string;
  timebox_minutes: number;
  goal: string;
  hints: Record<string, string>;
  bujo: Record<string, string>;
  highest_hint?: string;
  notes: string;
}

export interface Attempt {
  id: string;
  problem_id: number;
  assignment_id?: string;
  leetcode_id?: number;
  title: string;
  pattern_id?: string;
  occurred_on: string;
  result: Result;
  accepted: number;
  independent: number;
  duration_minutes?: number;
  highest_hint?: string;
  failure_tag?: string;
  explanation_score?: number;
}

export interface Review {
  id: string;
  problem_id: number;
  title: string;
  due_on: string;
  status: string;
  stage: string;
  pattern_id?: string;
}

export interface MemoryState {
  problem_id: number;
  title: string;
  pattern_id?: string;
  stability_days: number;
  difficulty: number;
  retrievability: number;
  evidence_count: number;
  last_attempt_on: string;
  next_due: string;
  last_result: string;
  curve: Array<{ day: number; value: number }>;
}

export interface PatternSummary {
  id: string;
  title: string;
  description: string;
  recognition_signals: string[];
  evidence_count: number;
  independent_count: number;
  red_count: number;
  confidence: string;
}

export interface TraceEvent {
  type: string;
  title?: string;
  copy: string;
  node?: number;
  from?: number;
  to?: number;
  tin?: number;
  low?: number;
  old?: number;
  new?: number;
  bridge?: boolean;
}

export interface Lesson {
  pattern: Record<string, unknown> & { title: string; invariant: string; failure_modes: string[] };
  graph: { nodes: Array<{ id: number; x: number; y: number }>; edges: number[][] };
  trace: TraceEvent[];
}

export interface ProblemSummary {
  id: number;
  leetcode_id?: number;
  slug: string;
  title: string;
  url?: string;
  difficulty?: string;
  pattern_id?: string;
  pattern_title?: string;
  queue_state?: string;
  status: string;
  priority?: number;
  roadmap_week?: number;
  roadmap_position?: number;
  evidence_count: number;
  independent_count: number;
  last_attempt_on?: string;
  last_result?: Result;
  next_due?: string;
  stability_days?: number;
}

export interface ProblemListResponse {
  items: ProblemSummary[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  status_counts: Record<string, number>;
}

export interface ProblemDetail {
  problem: ProblemSummary & {
    pattern_description?: string;
    recognition_signals: string[];
  };
  attempts: Attempt[];
  reviews: Review[];
  memory: Omit<MemoryState, "title" | "curve"> | null;
  active_assignment: Assignment | null;
  lesson: Lesson | null;
}

export interface Bootstrap {
  generated_at: string;
  today: string;
  timezone: string;
  active_assignment: Assignment | null;
  attempts: Attempt[];
  reviews: Review[];
  memory: MemoryState[];
  patterns: PatternSummary[];
  profile: Record<string, any> | null;
  lesson: Lesson | null;
  workload: {
    total: number;
    status_counts: Record<string, number>;
    preview: ProblemSummary[];
  };
  evidence: {
    count: number;
    outcomes: Record<string, number>;
    failures: Record<string, number>;
    independent_count: number;
    accepted_count: number;
    confidence: string;
  };
}
