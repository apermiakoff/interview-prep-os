import { useEffect, useState } from "react";
import { api } from "./api";
import type { Bootstrap } from "./types";
import { EvidenceView } from "./views/EvidenceView";
import { PatternsView } from "./views/PatternsView";
import { ProblemCollectionView } from "./views/ProblemCollectionView";
import { ProblemDetailView } from "./views/ProblemDetailView";
import { ProfileView } from "./views/ProfileView";
import { SolveView } from "./views/SolveView";
import { TodayView } from "./views/TodayView";

const navigation = [
  ["today", "Today"],
  ["queue", "Queue"],
  ["reviews", "Reviews"],
  ["problems", "Problems"],
  ["patterns", "Patterns"],
  ["evidence", "Evidence"],
] as const;

function currentRoute() {
  return window.location.hash.slice(1) || "today";
}

function routeLabel(route: string) {
  if (route.startsWith("problem/")) return "Problem";
  if (route === "solve") return "Solve Room";
  if (route === "profile") return "Profile";
  return navigation.find(([name]) => name === route)?.[1] || "Today";
}

export function App() {
  const [data, setData] = useState<Bootstrap | null>(null);
  const [route, setRoute] = useState(currentRoute());
  const [error, setError] = useState("");
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem("interview-prep-theme") || "ink"; }
    catch { return "ink"; }
  });

  useEffect(() => {
    api.bootstrap().then(setData).catch(reason => setError(reason instanceof Error ? reason.message : "Could not load the training system."));
  }, []);
  useEffect(() => {
    const onHash = () => setRoute(currentRoute());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("interview-prep-theme", theme); } catch { /* storage may be denied */ }
  }, [theme]);
  useEffect(() => {
    document.title = `${routeLabel(route)} · Interview Prep OS`;
    document.getElementById("main-content")?.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [route]);

  const navigate = (next: string) => {
    window.location.hash = next;
    setRoute(next);
  };

  if (error) return <div className="boot-state"><span className="brand-mark">IP</span><h1>Could not open the cockpit.</h1><p>{error}</p><button className="button primary" onClick={() => window.location.reload()}>Retry</button></div>;
  if (!data) return <div className="boot-state"><span className="brand-mark pulse">IP</span><h1>Preparing today’s retrieval…</h1></div>;

  const activeNav = route.startsWith("problem/") ? "problems" : route;
  const problemId = route.startsWith("problem/") ? Number(route.split("/")[1]) : null;

  return (
    <div className="app-shell">
      <header className="masthead">
        <button className="brand" onClick={() => navigate("today")} aria-label="Interview Prep OS home"><span className="brand-mark">IP</span><span><strong>Interview Prep</strong><em>Operating System</em></span></button>
        <nav aria-label="Primary navigation">{navigation.map(([name, label]) => <button key={name} onClick={() => navigate(name)} className={activeNav === name ? "active" : ""} aria-current={activeNav === name ? "page" : undefined}>{label}{name === "reviews" && (data.workload.status_counts.overdue || data.workload.status_counts.due) ? <i className="nav-count">{(data.workload.status_counts.overdue || 0) + (data.workload.status_counts.due || 0)}</i> : null}</button>)}</nav>
        <div className="masthead-actions"><span className="private-badge">private</span><button className="theme-toggle" aria-label="Toggle color theme" onClick={() => setTheme(value => value === "ink" ? "paper" : "ink")}><span /><span /></button><button className={`profile-button ${route === "profile" ? "active" : ""}`} onClick={() => navigate("profile")} aria-label="Profile">AP</button></div>
      </header>

      {route === "today" && <TodayView data={data} navigate={navigate} />}
      {route === "solve" && <SolveView data={data} onData={setData} navigate={navigate} />}
      {route === "queue" && <ProblemCollectionView data={data} navigate={navigate} scope="queue" eyebrow="Training control center" title="The queue, without the pile-up." description="Search, filter, and maintain every learning obligation. Only 25 rows are rendered at once." allowBulk />}
      {route === "reviews" && <ProblemCollectionView data={data} navigate={navigate} scope="reviews" eyebrow="Adaptive retrieval inbox" title="Reviews ordered by evidence." description="Overdue and upcoming reconstruction work, separated from the general roadmap." />}
      {route === "problems" && <ProblemCollectionView data={data} navigate={navigate} scope="all" eyebrow="Problem library" title="Every problem has its own history." description="Browse the roadmap and evidence without turning Today into a catalog." />}
      {route === "evidence" && <EvidenceView data={data} />}
      {route === "patterns" && <PatternsView data={data} navigate={navigate} />}
      {route === "profile" && <ProfileView data={data} />}
      {problemId != null && Number.isFinite(problemId) && <ProblemDetailView problemId={problemId} navigate={navigate} />}

      <footer><span>Private training system · append-only evidence</span><span>{data.workload.total} queued problems · generated {new Date(data.generated_at).toLocaleString("en", { timeZone: data.timezone, timeZoneName: "short" })}</span></footer>
    </div>
  );
}
