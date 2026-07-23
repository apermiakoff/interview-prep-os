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
import { AISetupView } from "./views/AISetupView";

const navigation = [
  ["today", "Today", "⌂"],
  ["brain", "Brain", "◈"],
  ["roadmap", "Roadmap", "⌘"],
  ["library", "Library", "▦"],
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
  // Bookmarks and hand-typed URLs often use #/solve; treat it as #solve.
  const raw = window.location.hash.slice(1).replace(/^\/+/, "") || "today";
  return legacyRoutes[raw] || raw;
}

function routeLabel(route: string) {
  if (route.startsWith("problem/")) return "Problem";
  if (route.startsWith("library")) return "Library";
  if (route.startsWith("solve")) return "Solve Room";
  if (route === "profile") return "Profile";
  if (route === "settings/ai") return "AI Setup";
  return navigation.find(([name]) => name === route)?.[1] || "Today";
}

type Theme = "light" | "dark";

function initialTheme(): Theme {
  try {
    const stored = localStorage.getItem("interview-prep-theme");
    if (stored === "light" || stored === "paper") return "light";
    if (stored === "dark" || stored === "ink") return "dark";
  } catch { /* storage may be denied */ }
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function App() {
  const [data, setData] = useState<Bootstrap | null>(null);
  const [route, setRoute] = useState(currentRoute());
  const [error, setError] = useState("");
  const [theme, setTheme] = useState<Theme>(initialTheme);

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
    document.documentElement.style.colorScheme = theme;
    try { localStorage.setItem("interview-prep-theme", theme); } catch { /* storage may be denied */ }
  }, [theme]);
  useEffect(() => {
    document.title = `${routeLabel(route)} · Interview Prep OS`;
    const main = document.getElementById("main-content");
    if (main) {
      main.tabIndex = -1;
      main.focus({ preventScroll: true });
    }
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [route]);

  const navigate = (next: string) => {
    window.location.hash = next;
    setRoute(legacyRoutes[next] || next);
  };
  // Swap the current history entry: the bare #solve compatibility route resolves
  // to a concrete session without trapping the back button in a redirect loop.
  const replaceRoute = (next: string) => {
    window.history.replaceState(null, "", `#${next}`);
    setRoute(next);
  };

  if (error) return <div className="boot-state"><span className="brand-mark">IP</span><h1>Could not open the cockpit.</h1><p>{error}</p><button className="button primary" onClick={() => window.location.reload()}>Retry</button></div>;
  if (!data) return <div className="boot-state"><span className="brand-mark pulse">IP</span><h1>Preparing today’s retrieval…</h1></div>;

  const activeNav = route.startsWith("problem/") ? "library" : route.startsWith("library") ? "library" : route;
  const problemId = route.startsWith("problem/") ? Number(route.split("/")[1]) : null;
  const sessionId = route.startsWith("solve/") ? route.slice("solve/".length) : null;
  const librarySub = route === "library/queue" ? "queue" : route === "library/reviews" ? "reviews" : "all";
  const dueCount = (data.workload.status_counts.overdue || 0) + (data.workload.status_counts.due || 0);

  return (
    <div className="app-shell">
      <aside className="activity-rail" aria-label="Application navigation">
        <button className="rail-brand" onClick={() => navigate("today")} aria-label="Interview Prep OS home"><span className="brand-mark">IP</span></button>
        <nav aria-label="Primary navigation">{navigation.map(([name, label, icon]) => <button key={name} onClick={() => navigate(name)} className={activeNav === name ? "active" : ""} aria-current={activeNav === name ? "page" : undefined}><span className="nav-icon" aria-hidden="true">{icon}</span><span className="nav-label">{label}</span>{name === "library" && dueCount ? <i className="nav-count">{dueCount}</i> : null}</button>)}</nav>
        <button className={`profile-button ${route === "profile" ? "active" : ""}`} onClick={() => navigate("profile")} aria-label="Open profile">AP</button>
      </aside>
      <header className="masthead">
        <button className="brand" onClick={() => navigate("today")} aria-label="Interview Prep OS home"><span className="brand-mark">IP</span><span><strong>Interview Prep OS</strong><em>Private workspace</em></span></button>
        <div className="context-title"><span>Workspace</span><strong>{routeLabel(route)}</strong></div>
        <nav aria-label="Primary navigation">{navigation.map(([name, label, icon]) => <button key={name} onClick={() => navigate(name)} className={activeNav === name ? "active" : ""} aria-current={activeNav === name ? "page" : undefined}><span aria-hidden="true">{icon}</span><span>{label}</span>{name === "library" && dueCount ? <i className="nav-count">{dueCount}</i> : null}</button>)}</nav>
        <div className="masthead-actions"><span className="private-badge">Local · private</span><button className="theme-toggle" type="button" aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} aria-pressed={theme === "light"} title={`Use ${theme === "dark" ? "light" : "dark"} theme`} onClick={() => setTheme(value => value === "dark" ? "light" : "dark")}><span aria-hidden="true">{theme === "dark" ? "☾" : "☀"}</span><span>{theme === "dark" ? "Dark" : "Light"}</span></button><button className={`profile-button ${route === "profile" ? "active" : ""}`} onClick={() => navigate("profile")} aria-label="Open profile">AP</button></div>
      </header>

      {route === "today" && <TodayView data={data} navigate={navigate} />}
      {(route === "solve" || sessionId) && <SolveView key={sessionId || "scheduled"} sessionId={sessionId} data={data} onData={setData} navigate={navigate} replaceRoute={replaceRoute} />}
      {route === "brain" && <BrainView data={data} navigate={navigate} />}
      {route === "roadmap" && <RoadmapView navigate={navigate} />}
      {route.startsWith("library") && <LibraryView data={data} navigate={navigate} sub={librarySub} />}
      {route === "profile" && <ProfileView data={data} navigate={navigate} />}
      {route === "settings/ai" && <AISetupView />}
      {problemId != null && Number.isFinite(problemId) && <ProblemDetailView problemId={problemId} data={data} navigate={navigate} />}

      <footer><span>Private training system · append-only evidence</span><span>{data.workload.total} queued problems · generated {new Date(data.generated_at).toLocaleString("en", { timeZone: data.timezone, timeZoneName: "short" })}</span></footer>
    </div>
  );
}
