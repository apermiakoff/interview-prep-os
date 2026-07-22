import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { Bootstrap, ProblemListResponse, ProblemSummary } from "../types";
import "../collection-workspace.css";

/*
 * One compact row per problem, search before status chrome, and a real
 * Practice action on every row. Ad hoc practice never touches the scheduled
 * assignment; the scheduled problem's row routes into its scheduled session.
 */

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

// Visible segments stay few; everything else remains reachable via More.
const SEGMENTS: Array<{ id: string; label: string; statuses: string[] }> = [
  { id: "due", label: "Due", statuses: ["overdue", "due"] },
  { id: "learning", label: "Learning", statuses: ["learning"] },
  { id: "backlog", label: "Backlog", statuses: ["backlog"] },
];

const MORE_STATUSES = ["active", "upcoming", "stable", "blocked", "catalog", "archived"];

function dueCopy(problem: ProblemSummary) {
  if (problem.status === "active") return "Focused session";
  if (problem.status === "overdue") return `Overdue · ${problem.next_due}`;
  if (problem.status === "due") return "Review today";
  if (problem.next_due) return `Review ${problem.next_due}`;
  if (problem.roadmap_week != null) return `Roadmap · week ${problem.roadmap_week}`;
  return "Not scheduled";
}

function externalUrl(problem: ProblemSummary) {
  return problem.url || `https://leetcode.com/problems/${problem.slug}/`;
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
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [response, setResponse] = useState<ProblemListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [launching, setLaunching] = useState<number | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const requestVersion = useRef(0);

  useEffect(() => {
    setPage(1);
    setSelected(new Set());
  }, [query, status, pattern, difficulty, track, sort, scope]);

  const listParams = useMemo(
    () => ({ search: query, status, pattern, difficulty, track, scope, sort, page_size: 25 }),
    [query, status, pattern, difficulty, track, scope, sort],
  );

  useEffect(() => {
    const version = ++requestVersion.current;
    let current = true;
    setLoading(true);
    setError("");
    const timer = window.setTimeout(() => {
      api.problems({ ...listParams, page }).then(result => {
        if (current && requestVersion.current === version) setResponse(result);
      }).catch(reason => {
        if (current && requestVersion.current === version) setError(reason instanceof Error ? reason.message : "Could not load problems.");
      }).finally(() => {
        if (current && requestVersion.current === version) setLoading(false);
      });
    }, 220);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [listParams, page]);

  const counts = response?.status_counts || {};
  const allCount = Object.entries(counts).reduce((sum, [value, count]) => sum + (value === "archived" ? 0 : count), 0);
  const segmentCount = (statuses: string[]) => statuses.reduce((sum, value) => sum + (counts[value] || 0), 0);
  const segmentValue = (statuses: string[]) => statuses.join(",");
  const moreValue = MORE_STATUSES.includes(status) ? status : "";
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
    const version = requestVersion.current;
    setBulkBusy(true);
    setError("");
    try {
      await api.updateQueue([...selected], state);
      setSelected(new Set());
      const refreshed = await api.problems({ ...listParams, page });
      if (requestVersion.current === version) setResponse(refreshed);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update the queue.");
    } finally {
      setBulkBusy(false);
    }
  };

  const startPractice = async (problem: ProblemSummary) => {
    setLaunching(problem.id);
    setError("");
    try {
      const envelope = await api.startProblemSession(problem.id);
      navigate(`solve/${envelope.session.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start the practice session.");
      setLaunching(null);
    }
  };

  // Random pick over the whole filtered set, then an ad hoc session — surprise
  // practice never replaces scheduled work.
  const surprise = async () => {
    if (!response || !response.total) return;
    setLaunching(-1);
    setError("");
    try {
      const index = Math.floor(Math.random() * response.total);
      const targetPage = Math.floor(index / response.page_size) + 1;
      let pool = response.items;
      if (targetPage !== response.page) {
        pool = (await api.problems({ ...listParams, page: targetPage })).items;
      }
      const pick = pool[index % response.page_size] ?? pool[0];
      if (!pick) return;
      const envelope = await api.startProblemSession(pick.id);
      navigate(`solve/${envelope.session.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start a surprise session.");
      setLaunching(null);
    }
  };

  return (
    <main className="view page-shell collection-view" id="main-content">
      <header className="collection-command-header">
        <div className="collection-command-title">
          <h1>{eyebrow}</h1><span aria-hidden="true">/</span><strong>{title}</strong>
          <span className="collection-result-count" role="status">{loading && !response ? "Loading" : `${response?.total ?? 0} result${response?.total === 1 ? "" : "s"}`}</span>
        </div>
        <p>{description}</p>
      </header>

      <section className={`collection-toolbar ${showTrackFilter ? "with-track-filter" : ""}`} aria-label="Problem filters">
        <label className="search-field"><span aria-hidden="true">⌕</span><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search title, #, or slug" aria-label="Search problems" /></label>
        {showTrackFilter && <label><span>Track</span><select value={track} onChange={event => setTrack(event.target.value)} aria-label="Track filter"><option value="">All tracks</option>{(response?.tracks || []).map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>}
        <label><span>Pattern</span><select value={pattern} onChange={event => setPattern(event.target.value)}><option value="">All patterns</option>{data.patterns.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
        <label><span>Difficulty</span><select value={difficulty} onChange={event => setDifficulty(event.target.value)}><option value="">Any difficulty</option><option>Easy</option><option>Medium</option><option>Hard</option></select></label>
        <label><span>Sort</span><select value={sort} onChange={event => setSort(event.target.value)}><option value="priority">Roadmap priority</option><option value="due">Next review</option><option value="recent">Recent activity</option><option value="evidence">Evidence count</option><option value="title">Title</option></select></label>
        <button className="surprise-button" disabled={!response?.total || launching !== null} onClick={surprise} title="Start focused practice from a random filtered problem">⚡ Random practice</button>
      </section>

      <section className="status-strip" aria-label="Status filters">
        <button className={!status ? "active" : ""} aria-pressed={!status} onClick={() => setStatus("")}><strong>{response ? allCount : "—"}</strong><span>All</span></button>
        {SEGMENTS.map(segment => {
          const value = segmentValue(segment.statuses);
          return (
            <button key={segment.id} className={status === value ? "active" : ""} aria-pressed={status === value} onClick={() => setStatus(status === value ? "" : value)}>
              <strong>{segmentCount(segment.statuses)}</strong><span>{segment.label}</span>
            </button>
          );
        })}
        <label className="status-more">
          <span>More</span>
          <select value={moreValue} aria-label="More status filters" onChange={event => setStatus(event.target.value)}>
            <option value="">Any status</option>
            {MORE_STATUSES.map(value => <option key={value} value={value}>{STATUS_COPY[value]}{counts[value] ? ` (${counts[value]})` : ""}</option>)}
          </select>
        </label>
      </section>

      {selected.size > 0 && allowBulk && <div className="bulk-bar"><strong>{selected.size} selected</strong><span>Move to</span><button disabled={bulkBusy} onClick={() => bulkUpdate("backlog")}>Backlog</button><button disabled={bulkBusy} onClick={() => bulkUpdate("blocked")}>Blocked</button><button disabled={bulkBusy} onClick={() => bulkUpdate("archived")}>Archive</button><button className="bulk-clear" disabled={bulkBusy} onClick={() => setSelected(new Set())}>Clear</button></div>}

      <section className={`problem-table ${allowBulk ? "with-bulk" : ""} ${loading ? "refreshing" : ""}`} aria-busy={loading}>
        {loading && response && <div className="table-refresh" role="status">Loading…</div>}
        <div className="problem-table-head">
          {allowBulk && <input type="checkbox" aria-label="Select page" checked={allSelected} onChange={() => setSelected(allSelected ? new Set() : new Set(response?.items.map(item => item.id) || []))} />}
          <span>Problem</span><span>Evidence</span><span>Status / schedule</span><span className="head-actions">Actions</span>
        </div>
        {error && <div className="empty-state">{error}</div>}
        {!error && loading && !response && <div className="collection-loading">Loading the library…</div>}
        {!error && response?.items.map(problem => <article className="problem-row" key={problem.id}>
          {allowBulk && <input type="checkbox" aria-label={`Select ${problem.title}`} checked={selected.has(problem.id)} disabled={problem.status === "active"} onChange={() => toggle(problem.id)} />}
          <button className="problem-identity" onClick={() => navigate(`problem/${problem.id}`)}>
            <span className="problem-title-line"><strong>{problem.title}</strong>{problem.difficulty && <i className={`difficulty-mark ${problem.difficulty.toLowerCase()}`}>{problem.difficulty}</i>}</span>
            <span>{problem.leetcode_id ? `#${problem.leetcode_id}` : "Personal"} · {problem.pattern_title || "Unclassified"}</span>
          </button>
          <span className="evidence-cell"><strong>{problem.evidence_count}</strong><small>{problem.independent_count} ind.</small></span>
          <span className="state-cell"><i className={`status-pill ${problem.status}`}>{STATUS_COPY[problem.status] || problem.status}</i><em>{dueCopy(problem)}</em></span>
          <span className="row-actions">
            <button className="practice-button" disabled={launching !== null} onClick={() => startPractice(problem)}>
              Practice
            </button>
            <a className="external-button" href={externalUrl(problem)} target="_blank" rel="noreferrer" aria-label={`Open ${problem.title} on LeetCode`}>↗</a>
          </span>
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
