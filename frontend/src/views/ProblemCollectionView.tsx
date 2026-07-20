import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { Bootstrap, ProblemListResponse, ProblemSummary } from "../types";

const STATUS_ORDER = [
  "active",
  "overdue",
  "due",
  "upcoming",
  "blocked",
  "learning",
  "backlog",
  "stable",
  "archived",
  "catalog",
];

const STATUS_COPY: Record<string, string> = {
  active: "Active",
  overdue: "Overdue",
  due: "Due today",
  upcoming: "Upcoming",
  blocked: "Blocked",
  learning: "Learning",
  backlog: "Backlog",
  stable: "Stable",
  archived: "Archived",
  catalog: "Catalog",
};

function dueCopy(problem: ProblemSummary) {
  if (problem.status === "active") return "Continue session";
  if (problem.status === "overdue") return `Overdue · ${problem.next_due}`;
  if (problem.status === "due") return "Review today";
  if (problem.next_due) return `Review ${problem.next_due}`;
  if (problem.roadmap_week != null) return `Roadmap · week ${problem.roadmap_week}`;
  return "Not scheduled";
}

interface Props {
  data: Bootstrap;
  navigate: (route: string) => void;
  scope: "all" | "queue" | "reviews";
  eyebrow: string;
  title: string;
  description: string;
  allowBulk?: boolean;
  showTrackFilter?: boolean;
}

export function ProblemCollectionView({
  data,
  navigate,
  scope,
  eyebrow,
  title,
  description,
  allowBulk = false,
  showTrackFilter = false,
}: Props) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [pattern, setPattern] = useState("");
  const [difficulty, setDifficulty] = useState("");
  const [track, setTrack] = useState("");
  const [sort, setSort] = useState(scope === "reviews" ? "due" : "priority");
  const [page, setPage] = useState(1);
  const [density, setDensity] = useState<"comfortable" | "compact">("comfortable");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [response, setResponse] = useState<ProblemListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setPage(1);
    setSelected(new Set());
  }, [query, status, pattern, difficulty, track, sort, scope]);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError("");
    const timer = window.setTimeout(() => {
      api.problems({
        search: query,
        status,
        pattern,
        difficulty,
        track,
        scope,
        sort,
        page,
        page_size: 25,
      }).then(result => {
        if (current) setResponse(result);
      }).catch(reason => {
        if (current) setError(reason instanceof Error ? reason.message : "Could not load problems.");
      }).finally(() => {
        if (current) setLoading(false);
      });
    }, 220);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [query, status, pattern, difficulty, track, sort, scope, page]);

  const counts = response?.status_counts || {};
  const visibleStatuses = STATUS_ORDER.filter(value => counts[value]);
  const allSelected = Boolean(response?.items.length) && response!.items.every(item => selected.has(item.id));
  const resultLabel = useMemo(() => {
    if (!response) return "Loading…";
    const from = response.total ? (response.page - 1) * response.page_size + 1 : 0;
    const to = Math.min(response.total, response.page * response.page_size);
    return `${from}–${to} of ${response.total}`;
  }, [response]);

  const toggle = (problemId: number) => {
    setSelected(previous => {
      const next = new Set(previous);
      if (next.has(problemId)) next.delete(problemId);
      else next.add(problemId);
      return next;
    });
  };

  const bulkUpdate = async (state: string) => {
    if (!selected.size) return;
    await api.updateQueue([...selected], state);
    setSelected(new Set());
    const refreshed = await api.problems({ search: query, status, pattern, difficulty, scope, sort, page, page_size: 25 });
    setResponse(refreshed);
  };

  return (
    <main className="view page-shell collection-view" id="main-content">
      <header className="collection-heading">
        <div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>
        <div className="collection-total"><strong>{response?.total ?? "—"}</strong><span>{scope === "reviews" ? "review obligations" : "problems"}</span></div>
      </header>

      <section className="status-facets" aria-label="Status filters">
        <button className={!status ? "active" : ""} onClick={() => setStatus("")}><strong>{response ? Object.entries(counts).reduce((sum, [value, count]) => sum + (value === "archived" ? 0 : count), 0) : "—"}</strong><span>All</span></button>
        {visibleStatuses.map(value => <button key={value} className={status === value ? "active" : ""} onClick={() => setStatus(status === value ? "" : value)}><strong>{counts[value]}</strong><span>{STATUS_COPY[value]}</span></button>)}
      </section>

      <section className="collection-toolbar" aria-label="Problem filters">
        <label className="search-field"><span aria-hidden="true">⌕</span><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search title or slug…" aria-label="Search problems" /></label>
        {showTrackFilter && <label><span>Track</span><select value={track} onChange={event => setTrack(event.target.value)} aria-label="Track filter"><option value="">All tracks</option>{(response?.tracks || []).map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>}
        <label><span>Pattern</span><select value={pattern} onChange={event => setPattern(event.target.value)}><option value="">All patterns</option>{data.patterns.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
        <label><span>Difficulty</span><select value={difficulty} onChange={event => setDifficulty(event.target.value)}><option value="">Any difficulty</option><option>Easy</option><option>Medium</option><option>Hard</option></select></label>
        <label><span>Sort</span><select value={sort} onChange={event => setSort(event.target.value)}><option value="priority">Roadmap priority</option><option value="due">Next review</option><option value="recent">Recent activity</option><option value="evidence">Evidence count</option><option value="title">Title</option></select></label>
        <div className="density-toggle" aria-label="List density"><button className={density === "comfortable" ? "active" : ""} onClick={() => setDensity("comfortable")} aria-label="Comfortable list">☰</button><button className={density === "compact" ? "active" : ""} onClick={() => setDensity("compact")} aria-label="Compact list">≡</button></div>
      </section>

      {selected.size > 0 && allowBulk && <div className="bulk-bar"><strong>{selected.size} selected</strong><span>Move to</span><button onClick={() => bulkUpdate("backlog")}>Backlog</button><button onClick={() => bulkUpdate("blocked")}>Blocked</button><button onClick={() => bulkUpdate("archived")}>Archive</button><button className="bulk-clear" onClick={() => setSelected(new Set())}>Clear</button></div>}

      <section className={`problem-table ${density} ${allowBulk ? "with-bulk" : ""}`} aria-busy={loading}>
        <div className="problem-table-head">
          {allowBulk && <input type="checkbox" aria-label="Select page" checked={allSelected} onChange={() => setSelected(allSelected ? new Set() : new Set(response?.items.map(item => item.id) || []))} />}
          <span>Problem</span><span>Pattern</span><span>State</span><span>Evidence</span><span>Next action</span>
        </div>
        {error && <div className="empty-state">{error}</div>}
        {!error && loading && !response && <div className="collection-loading">Loading the queue…</div>}
        {!error && response?.items.map(problem => <article className="problem-row" key={problem.id}>
          {allowBulk && <input type="checkbox" aria-label={`Select ${problem.title}`} checked={selected.has(problem.id)} disabled={problem.status === "active"} onChange={() => toggle(problem.id)} />}
          <button className="problem-identity" onClick={() => navigate(`problem/${problem.id}`)}><strong>{problem.title}</strong><span>{problem.leetcode_id ? `#${problem.leetcode_id}` : problem.roadmap_week != null ? `Roadmap week ${problem.roadmap_week}` : "Personal catalog"}{problem.difficulty ? ` · ${problem.difficulty}` : ""}</span></button>
          <span className="table-pattern">{problem.pattern_title || "Unclassified"}</span>
          <span><i className={`status-pill ${problem.status}`}>{STATUS_COPY[problem.status] || problem.status}</i></span>
          <span className="evidence-cell"><strong>{problem.evidence_count}</strong><small>{problem.independent_count} independent</small></span>
          <span className="next-action">{dueCopy(problem)}</span>
        </article>)}
        {!error && !loading && response?.items.length === 0 && <div className="empty-state">No problems match these filters.</div>}
      </section>

      <footer className="collection-pagination">
        <span>{resultLabel} · maximum 25 rendered</span>
        <div><button disabled={!response || response.page <= 1} onClick={() => setPage(value => Math.max(1, value - 1))}>← Previous</button><span>Page {response?.page || 1} / {response?.pages || 1}</span><button disabled={!response || response.page >= response.pages} onClick={() => setPage(value => value + 1)}>Next →</button></div>
      </footer>
    </main>
  );
}
