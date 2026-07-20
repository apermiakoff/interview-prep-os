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

export interface TrackSummary {
  id: string;
  title: string;
  kind: string;
  priority: number;
}

export interface ProblemListResponse {
  items: ProblemSummary[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  status_counts: Record<string, number>;
  tracks: TrackSummary[];
}

export type DimensionState =
  | "no_evidence"
  | "fragile"
  | "developing"
  | "independent"
  | "decaying"
  | "blocked";

export interface SkillStateCell {
  state: DimensionState;
  evidence_count: number;
  independent_count: number;
  last_evidence_on?: string | null;
  facts?: string[];
  action?: string;
  updated_at?: string;
}

export interface ProblemSkill {
  skill_id: string;
  role: "core" | "supporting" | "variation";
  weight: number;
  provenance: string;
  title: string;
  kind?: string;
  parent_id?: string | null;
  states: Record<string, SkillStateCell>;
}

export interface Placement {
  curriculum_id: string;
  curriculum_title: string;
  kind: string;
  priority: number;
  week_label?: string | null;
  section: string;
  topic: string;
  position: number;
  confidence: string;
  source_screenshot?: string | null;
}

export interface RelatedProblem {
  id: number;
  leetcode_id?: number;
  slug: string;
  title: string;
  difficulty?: string;
  shared_skill: string;
  attempt_count: number;
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
  lesson_availability: { status: "authored" | "none"; label: string };
  skills: ProblemSkill[];
  prerequisites: Array<{ skill_id: string; title: string; weight: number; states: Record<string, SkillStateCell> }>;
  related_problems: RelatedProblem[];
  placements: Placement[];
}

export interface Trap {
  id: string;
  title: string;
  status: "recurring" | "suspected";
  observation_count: number;
  evidence: Array<{ attempt_id: string; occurred_on: string; problem: string; error_type?: string }>;
  intervention: string;
}

export interface MemoryRisk {
  problem_id: number;
  title: string;
  leetcode_id?: number;
  stability_days: number;
  retention_now: number;
  target_retention: number;
  target_due_on: string;
  days_since_attempt: number;
  evidence_count: number;
  last_result: string;
}

export interface LearningToday {
  decision_id: string;
  date: string;
  policy_version: string;
  target_retention: number;
  selected: {
    problem_id: number;
    leetcode_id?: number;
    slug: string;
    title: string;
    difficulty?: string;
    url?: string;
    components: Record<string, number>;
    score: number;
    gated: boolean;
    facts: string[];
    estimated_minutes: number;
  } | null;
  why: string[];
  components: Record<string, number>;
  weights: Record<string, number>;
  risk: Trap | null;
  traps_note: string | null;
  due_count: number;
  next_gate: {
    skill_id: string;
    dimension: string;
    current_state: string;
    criterion: string;
  } | null;
  active_assignment: { assignment_id: string; problem_id: number; assigned_on: string } | null;
  candidates_considered: number;
  runners_up: Array<{ problem_id: number; title: string; score: number; gated: boolean }>;
}

export interface LearningProfile {
  generated_at: string;
  policy_version: string;
  target_retention: number;
  confidence: string;
  evidence_summary: { attempts: number; dimension_observations: number; note: string };
  skills: Array<{
    id: string;
    title: string;
    kind?: string;
    parent_id?: string | null;
    provenance?: string;
    dimensions: Record<string, SkillStateCell>;
    evidence_count: number;
    weakness: number;
    readiness: number;
  }>;
  traps: Trap[];
  traps_note: string | null;
  memory_at_risk: MemoryRisk[];
}

export interface RoadmapItem {
  id: number;
  curriculum_id: string;
  import_key: string;
  problem_id: number | null;
  item_kind: string;
  section: string;
  topic: string;
  week_label?: string | null;
  position: number;
  title_raw: string;
  status_seen?: string | null;
  points_seen?: number | null;
  source_screenshot?: string | null;
  confidence: string;
  provenance: Record<string, unknown>;
  problem_title?: string | null;
  leetcode_id?: number | null;
  slug?: string | null;
  difficulty?: string | null;
  attempt_count: number;
  independent_count: number;
  evidence_status: "untouched" | "attempted" | "independent";
}

export interface LearningRoadmap {
  generated_at: string;
  policy_version: string;
  dimensions: string[];
  tracks: Array<TrackSummary & {
    description: string;
    provenance: Record<string, unknown>;
    items: RoadmapItem[];
    problem_count: number;
  }>;
  heatmap: Array<{
    skill_id: string;
    title: string;
    kind?: string;
    parent_id?: string | null;
    problem_count: number;
    dimensions: Record<string, SkillStateCell>;
  }>;
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
