import { useEffect, useState } from "react";
import { api } from "./api";
import type { Bootstrap } from "./types";
import { EvidenceView } from "./views/EvidenceView";
import { LabView } from "./views/LabView";
import { PatternsView } from "./views/PatternsView";
import { ProfileView } from "./views/ProfileView";
import { SolveView } from "./views/SolveView";
import { TodayView } from "./views/TodayView";

const routes = [
  ["today", "Today"],
  ["solve", "Solve Room"],
  ["evidence", "Evidence"],
  ["patterns", "Patterns"],
  ["lab", "Visual Lab"],
  ["profile", "Profile"],
] as const;

type Route = typeof routes[number][0];

function currentRoute(): Route {
  const value = window.location.hash.slice(1) as Route;
  return routes.some(([route]) => route === value) ? value : "today";
}

export function App() {
  const [data, setData] = useState<Bootstrap | null>(null);
  const [route, setRoute] = useState<Route>(currentRoute());
  const [error, setError] = useState("");
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem("interview-prep-theme") || "ink"; }
    catch { return "ink"; }
  });

  useEffect(() => {
    api.bootstrap().then(setData).catch(error => setError(error instanceof Error ? error.message : "Could not load the training system."));
  }, []);
  useEffect(() => {
    const onHash = () => setRoute(currentRoute());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("interview-prep-theme", theme); } catch { /* private file/storage policy */ }
  }, [theme]);
  useEffect(() => {
    const label = routes.find(([name]) => name === route)?.[1] || "Today";
    document.title = `${label} · Interview Prep OS`;
    document.getElementById("main-content")?.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [route]);

  const navigate = (next: string) => {
    window.location.hash = next;
    setRoute(next as Route);
  };

  if (error) return <div className="boot-state"><span className="brand-mark">IP</span><h1>Could not open the cockpit.</h1><p>{error}</p><button className="button primary" onClick={() => window.location.reload()}>Retry</button></div>;
  if (!data) return <div className="boot-state"><span className="brand-mark pulse">IP</span><h1>Preparing today’s retrieval…</h1></div>;

  return (
    <div className="app-shell">
      <header className="masthead">
        <button className="brand" onClick={() => navigate("today")} aria-label="Interview Prep OS home"><span className="brand-mark">IP</span><span><strong>Interview Prep</strong><em>Operating System</em></span></button>
        <nav aria-label="Primary navigation">{routes.map(([name, label]) => <button key={name} onClick={() => navigate(name)} className={route === name ? "active" : ""} aria-current={route === name ? "page" : undefined}>{label}</button>)}</nav>
        <div className="masthead-actions"><span className="private-badge">private</span><button className="theme-toggle" aria-label="Toggle color theme" onClick={() => setTheme(value => value === "ink" ? "paper" : "ink")}><span /><span /></button></div>
      </header>
      {route === "today" && <TodayView data={data} navigate={navigate} />}
      {route === "solve" && <SolveView data={data} onData={setData} navigate={navigate} />}
      {route === "evidence" && <EvidenceView data={data} />}
      {route === "patterns" && <PatternsView data={data} navigate={navigate} />}
      {route === "lab" && <LabView data={data} />}
      {route === "profile" && <ProfileView data={data} />}
      <footer><span>Private training artifact · append-only evidence</span><span>Generated {new Date(data.generated_at).toLocaleString("en", { timeZone: data.timezone, timeZoneName: "short" })}</span></footer>
    </div>
  );
}
