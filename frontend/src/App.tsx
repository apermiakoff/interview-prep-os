import { useEffect, useState } from "react";
import { api } from "./api";
import type { Bootstrap } from "./types";
import { BrainView } from "./views/BrainView";
import { LibraryView } from "./views/LibraryView";
import { ProblemDetailView } from "./views/ProblemDetailView";
import { ProfileView } from "./views/ProfileView";
import { RoadmapView } from "./views/RoadmapView";
import { SolveView } from "./views/SolveView";
import { TodayView } from "./views/TodayView";

const navigation = [
  ["today", "Today"],
  ["brain", "Brain"],
  ["roadmap", "Roadmap"],
  ["library", "Library"],
] as const;

// Old bookmarks and in-app links keep working after the IA change.
const legacyRoutes: Record<string, string> = {
  queue: "library/queue",
  reviews: "library/reviews",
  problems: "library",
  evidence: "brain",
  patterns: "roadmap",
  lab: "today",
};

function currentRoute() {
  const raw = window.location.hash.slice(1) || "today";
  return legacyRoutes[raw] || raw;
}

function routeLabel(route: string) {
  if (route.startsWith("problem/")) return "Problem";
  if (route.startsWith("library")) return "Library";
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
    setRoute(legacyRoutes[next] || next);
  };

  if (error) return <div className="boot-state"><span className="brand-mark">IP</span><h1>Could not open the cockpit.</h1><p>{error}</p><button className="button primary" onClick={() => window.location.reload()}>Retry</button></div>;
  if (!data) return <div className="boot-state"><span className="brand-mark pulse">IP</span><h1>Preparing today’s retrieval…</h1></div>;

  const activeNav = route.startsWith("problem/") ? "library" : route.startsWith("library") ? "library" : route;
  const problemId = route.startsWith("problem/") ? Number(route.split("/")[1]) : null;
  const librarySub = route === "library/queue" ? "queue" : route === "library/reviews" ? "reviews" : "all";
  const dueCount = (data.workload.status_counts.overdue || 0) + (data.workload.status_counts.due || 0);

  return (
    <div className="app-shell">
      <header className="masthead">
        <button className="brand" onClick={() => navigate("today")} aria-label="Interview Prep OS home"><span className="brand-mark">IP</span><span><strong>Interview Prep</strong><em>Operating System</em></span></button>
        <nav aria-label="Primary navigation">{navigation.map(([name, label]) => <button key={name} onClick={() => navigate(name)} className={activeNav === name ? "active" : ""} aria-current={activeNav === name ? "page" : undefined}>{label}{name === "library" && dueCount ? <i className="nav-count">{dueCount}</i> : null}</button>)}</nav>
        <div className="masthead-actions"><span className="private-badge">private</span><button className="theme-toggle" aria-label="Toggle color theme" onClick={() => setTheme(value => value === "ink" ? "paper" : "ink")}><span /><span /></button><button className={`profile-button ${route === "profile" ? "active" : ""}`} onClick={() => navigate("profile")} aria-label="Profile">AP</button></div>
      </header>

      {route === "today" && <TodayView data={data} navigate={navigate} />}
      {route === "solve" && <SolveView data={data} onData={setData} navigate={navigate} />}
      {route === "brain" && <BrainView data={data} navigate={navigate} />}
      {route === "roadmap" && <RoadmapView navigate={navigate} />}
      {route.startsWith("library") && <LibraryView data={data} navigate={navigate} sub={librarySub} />}
      {route === "profile" && <ProfileView data={data} />}
      {problemId != null && Number.isFinite(problemId) && <ProblemDetailView problemId={problemId} navigate={navigate} />}

      <footer><span>Private training system · append-only evidence</span><span>{data.workload.total} queued problems · generated {new Date(data.generated_at).toLocaleString("en", { timeZone: data.timezone, timeZoneName: "short" })}</span></footer>
    </div>
  );
}
