import { useState } from "react";
import { api } from "../api";
import type { Bootstrap, LearnerSettings } from "../types";

const empty: LearnerSettings = {
  display_name: "", interview_target: "", weekly_hours: 5, timezone: "UTC",
  weak_areas: [], preferred_language: "",
};

export function ProfileView({ data, navigate }: { data: Bootstrap; navigate: (route: string) => void }) {
  const [settings, setSettings] = useState<LearnerSettings>(data.learner || empty);
  const [saved, setSaved] = useState(false);
  const publicSnapshot = data.profile;
  const publicProfile = publicSnapshot?.profile || publicSnapshot;
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSettings(await api.saveLearnerSettings(settings));
    setSaved(true);
  };
  return <main className="view page-shell" id="main-content">
    <div className="profile-hero">
      <div className="profile-mark">{settings.display_name ? settings.display_name.split(/\s+/).map(p => p[0]).slice(0, 2).join("") : "IP"}</div>
      <div><span className="eyebrow">Local learner profile</span><h1>{settings.display_name || "Set up your profile"}</h1>
        <p>{settings.interview_target || "Add your target and schedule to personalize this private installation."}</p></div>
    </div>
    <section className="settings-link">
      <form onSubmit={submit} style={{ width: "100%" }}>
        <span className="eyebrow">Learner settings</span>
        <p><label>Display name<br/><input aria-label="Display name" value={settings.display_name} onChange={e => setSettings({...settings, display_name: e.target.value})}/></label></p>
        <p><label>Interview target<br/><input aria-label="Interview target" value={settings.interview_target} onChange={e => setSettings({...settings, interview_target: e.target.value})}/></label></p>
        <p><label>Weekly hours<br/><input aria-label="Weekly hours" type="number" min="1" max="80" value={settings.weekly_hours} onChange={e => setSettings({...settings, weekly_hours: Number(e.target.value)})}/></label></p>
        <p><label>Timezone (IANA)<br/><input aria-label="Timezone" value={settings.timezone} onChange={e => setSettings({...settings, timezone: e.target.value})}/></label></p>
        <p><label>Weak areas (comma separated)<br/><input aria-label="Weak areas" value={settings.weak_areas.join(", ")} onChange={e => setSettings({...settings, weak_areas: e.target.value.split(",").map(v => v.trim()).filter(Boolean)})}/></label></p>
        <p><label>Preferred language<br/><input aria-label="Preferred language" value={settings.preferred_language} onChange={e => setSettings({...settings, preferred_language: e.target.value})}/></label></p>
        <button className="button" type="submit">Save learner settings</button>{saved && <span role="status"> Saved locally.</span>}
      </form>
    </section>
    <section className="settings-link"><div><span className="eyebrow">Settings</span><h2>Community AI</h2><p>Optional server-side provider status and limits.</p></div><button className="button subtle" onClick={() => navigate("settings/ai")}>AI Setup →</button></section>
    {publicProfile ? <section className="profile-context"><article><span className="eyebrow">Optional public LeetCode snapshot</span><h2>@{publicProfile.username || "profile"}</h2><p>Public platform context remains separate from private learning evidence.</p></article></section> : <section className="profile-context"><article><span className="eyebrow">Public profile</span><h2>No public profile imported</h2><p>This is expected on a fresh install and does not limit practice.</p></article></section>}
  </main>;
}
