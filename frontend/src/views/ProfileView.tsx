import type { Bootstrap } from "../types";

export function ProfileView({ data, navigate }: { data: Bootstrap; navigate: (route: string) => void }) {
  const snapshot = data.profile || {};
  const profile = snapshot.profile || snapshot;
  const solved = snapshot.problem_stats || profile.stats?.solved || profile.solved || {};
  const all = solved.all || { count: 0, submissions: 0 };
  const easy = solved.easy || { count: 0 };
  const medium = solved.medium || { count: 0 };
  const hard = solved.hard || { count: 0 };
  const contest = snapshot.contest_stats || snapshot.contest || {};
  const total = Math.max(1, Number(all.count || 0));
  const percentile = Number(contest.top_percentage || contest.topPercentage || 0);
  const history = contest.history || [];
  const last = history.at(-1);

  return (
    <main className="view page-shell" id="main-content">
      <div className="profile-hero">
        <div className="profile-mark">{(profile.real_name || profile.username || "IP").split(/\s+/).map((part: string) => part[0]).slice(0, 2).join("")}</div>
        <div><span className="eyebrow">Public LeetCode context</span><h1>@{profile.username || "profile"}</h1><p>{[profile.real_name, profile.company, profile.country].filter(Boolean).join(" · ")}</p></div>
        {snapshot.source?.profile_url && <a className="button subtle" href={snapshot.source.profile_url} target="_blank" rel="noreferrer">Open public profile ↗</a>}
      </div>
      <section className="settings-link"><div><span className="eyebrow">Settings</span><h2>Community AI</h2><p>Server-side provider status, limits, and Docker setup guidance.</p></div><button className="button subtle" onClick={() => navigate("settings/ai")}>AI Setup →</button></section>
      <section className="profile-metrics"><article><span>Problems solved</span><strong>{Number(all.count || 0).toLocaleString()}</strong><p>Public footprint, not mastery evidence</p></article><article><span>Problem ranking</span><strong>#{Number(profile.ranking || 0).toLocaleString()}</strong><p>Platform-wide public rank</p></article><article><span>Contest rating</span><strong>{contest.rating ? Math.round(contest.rating).toLocaleString() : "—"}</strong><p>{percentile ? `Top ${percentile.toFixed(2)}%` : "No percentile"}</p></article></section>
      <section className="difficulty-composition"><div className="section-rule"><span>Difficulty composition</span><span>{total} total</span></div><div className="difficulty-track"><i className="easy" style={{ width: `${Number(easy.count || 0) / total * 100}%` }} /><i className="medium" style={{ width: `${Number(medium.count || 0) / total * 100}%` }} /><i className="hard" style={{ width: `${Number(hard.count || 0) / total * 100}%` }} /></div><div className="difficulty-labels"><span><i className="easy" />Easy <strong>{easy.count || 0}</strong></span><span><i className="medium" />Medium <strong>{medium.count || 0}</strong></span><span><i className="hard" />Hard <strong>{hard.count || 0}</strong></span></div></section>
      <section className="profile-context"><article><span className="eyebrow">Contest position</span><h2>{percentile ? `Ahead of ${(100 - percentile).toFixed(1)}% of ranked participants` : "Contest evidence is sparse"}</h2><div className="percentile-track"><i style={{ width: `${Math.max(0, Math.min(100, 100 - percentile))}%` }} /></div><p>Contest rating and solved totals remain separate from private retrieval evidence.</p></article><article><span className="eyebrow">Latest contest</span>{last ? <><h2>{last.title}</h2><p>{last.problems_solved} / {last.total_problems} solved · rank #{Number(last.ranking).toLocaleString()}</p><p>Rating trend {String(last.trend || "unknown").toLowerCase()}</p></> : <p>No attended contest snapshot.</p>}</article></section>
    </main>
  );
}
