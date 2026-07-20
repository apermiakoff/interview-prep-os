import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { LearningRoadmap, RoadmapItem, SkillStateCell } from "../types";

const DIMENSION_LABELS: Record<string, string> = {
  recognition: "Recognize",
  derivation: "Derive",
  implementation: "Implement",
  testing: "Test",
  explanation: "Explain",
  retention: "Retain",
};

const STATE_SHORT: Record<string, string> = {
  no_evidence: "—",
  fragile: "fragile",
  developing: "devel.",
  independent: "indep.",
  decaying: "decay",
  blocked: "blocked",
};

function groupItems(items: RoadmapItem[]) {
  const groups = new Map<string, RoadmapItem[]>();
  for (const item of items) {
    const key = item.week_label || item.section || "Ungrouped";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(item);
  }
  return [...groups.entries()];
}

export function RoadmapView({ navigate }: { navigate: (route: string) => void }) {
  const [roadmap, setRoadmap] = useState<LearningRoadmap | null>(null);
  const [error, setError] = useState("");
  const [selectedCell, setSelectedCell] = useState<{ skill: string; title: string; dimension: string; cell: SkillStateCell } | null>(null);
  const [openTrack, setOpenTrack] = useState<string | null>(null);

  useEffect(() => {
    api.learningRoadmap().then(payload => {
      setRoadmap(payload);
      setOpenTrack(payload.tracks[0]?.id ?? null);
    }).catch(reason => setError(reason instanceof Error ? reason.message : "Could not load the roadmap."));
  }, []);

  const heatmapRows = useMemo(() => {
    if (!roadmap) return [];
    return [...roadmap.heatmap]
      .filter(row => row.problem_count > 0)
      .sort((a, b) => {
        const evidence = (row: typeof a) => Object.values(row.dimensions).reduce((sum, cell) => sum + cell.evidence_count, 0);
        return evidence(b) - evidence(a) || a.skill_id.localeCompare(b.skill_id);
      });
  }, [roadmap]);

  if (error) return <main className="view page-shell" id="main-content"><div className="empty-state">{error}</div></main>;
  if (!roadmap) return <main className="view page-shell" id="main-content"><div className="collection-loading">Loading roadmap…</div></main>;

  return (
    <main className="view page-shell roadmap-page" id="main-content">
      <div className="section-heading compact">
        <span className="eyebrow">Roadmap · tracks and competency</span>
        <h1>Two tracks, one honest competency map.</h1>
        <p>The formal Outtalent program ranks above the deep supplemental roadmap. Heatmap cells state their evidence count; nothing is a percentage.</p>
      </div>

      <section className="competency" aria-label="Competency heatmap">
        <div className="section-rule"><span>Competency heatmap</span><span>{heatmapRows.length} skills with mapped problems</span></div>
        <div className="heatmap-scroll">
          <table className="heatmap">
            <thead>
              <tr>
                <th scope="col">Skill</th>
                {roadmap.dimensions.map(dimension => <th key={dimension} scope="col">{DIMENSION_LABELS[dimension] || dimension}</th>)}
              </tr>
            </thead>
            <tbody>
              {heatmapRows.map(row => (
                <tr key={row.skill_id}>
                  <th scope="row"><span className="heat-skill">{row.title}</span><span className="heat-meta">{row.problem_count} problem{row.problem_count === 1 ? "" : "s"}</span></th>
                  {roadmap.dimensions.map(dimension => {
                    const cell = row.dimensions[dimension];
                    const active = selectedCell?.skill === row.skill_id && selectedCell.dimension === dimension;
                    return (
                      <td key={dimension}>
                        <button
                          className={`heat-cell ${cell.state} ${active ? "selected" : ""}`}
                          onClick={() => setSelectedCell({ skill: row.skill_id, title: row.title, dimension, cell })}
                          aria-label={`${row.title} ${DIMENSION_LABELS[dimension]}: ${cell.state.replace("_", " ")}, ${cell.evidence_count} observations`}
                        >
                          <span className="heat-state">{STATE_SHORT[cell.state]}</span>
                          {cell.evidence_count > 0 && <span className="heat-count">{cell.evidence_count}</span>}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="heatmap-detail" role="status">
          {selectedCell ? (
            <>
              <strong>{selectedCell.title} · {DIMENSION_LABELS[selectedCell.dimension]}</strong>
              <span className={`chip ${selectedCell.cell.state === "independent" ? "stable" : selectedCell.cell.state === "no_evidence" ? "neutral" : "recurring"}`}>{selectedCell.cell.state.replace("_", " ")} · {selectedCell.cell.evidence_count} obs</span>
              <p>{selectedCell.cell.action}</p>
            </>
          ) : (
            <p className="quiet-note">Select a cell to see its evidence and the next action. States: no evidence, fragile, developing, independent, decaying, blocked.</p>
          )}
        </div>
      </section>

      {roadmap.tracks.map(track => {
        const open = openTrack === track.id;
        const attempted = track.items.filter(item => item.evidence_status !== "untouched" && item.problem_id != null).length;
        return (
          <section className="track" key={track.id}>
            <button className="track-header" onClick={() => setOpenTrack(open ? null : track.id)} aria-expanded={open}>
              <div>
                <span className="eyebrow">{track.kind === "formal" ? "Formal priority" : "Supplemental depth"}</span>
                <h2>{track.title}</h2>
              </div>
              <div className="track-facts">
                <span>{track.problem_count} problems</span>
                <span>{attempted} with evidence</span>
                <span className="disclose">{open ? "Hide" : "Show"}</span>
              </div>
            </button>
            {open && (
              <>
                <p className="track-provenance">{track.description}</p>
                {groupItems(track.items).map(([group, items]) => (
                  <div className="track-group" key={group}>
                    <div className="section-rule"><span>{group}</span><span>{items.filter(item => item.problem_id != null).length} problems · {items.length} items</span></div>
                    {items.map(item => (
                      item.problem_id != null ? (
                        <button key={item.import_key} className="track-line" onClick={() => navigate(`problem/${item.problem_id}`)}>
                          <span className="track-num">{item.leetcode_id ? `#${item.leetcode_id}` : "—"}</span>
                          <strong>{item.problem_title}</strong>
                          <em>{item.topic || item.section}</em>
                          <i className={`status-pill ${item.evidence_status === "independent" ? "stable" : item.evidence_status === "attempted" ? "learning" : "backlog"}`}>{item.evidence_status}</i>
                        </button>
                      ) : (
                        <div key={item.import_key} className="track-line non-problem">
                          <span className="track-num">·</span>
                          <strong>{item.title_raw}</strong>
                          <em>{item.item_kind}{item.item_kind === "placeholder" ? " · no problem number in source" : ""}</em>
                          <i className="status-pill catalog">{item.item_kind}</i>
                        </div>
                      )
                    ))}
                  </div>
                ))}
              </>
            )}
          </section>
        );
      })}

      <p className="policy-note">Curriculum provenance: Outtalent items were extracted manually from Campus screenshots with per-row confidence; the deep track mirrors the legacy study plan. Rows without a readable problem number are shown as non-problem items, never invented.</p>
    </main>
  );
}
