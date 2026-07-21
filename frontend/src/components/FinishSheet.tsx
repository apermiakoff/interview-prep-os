import { useEffect, useMemo, useRef, useState } from "react";
import type { Result } from "../types";

/*
 * Finish attempt sheet. One mutually exclusive outcome first; the facts follow.
 * Independence is derived from the outcome and recorded hint use — there is no
 * contradictory checkbox — and the final line previews the exact record before
 * the single submit button writes it.
 */

export type Outcome = "independent" | "assisted" | "solution" | "skipped";

export interface FinishFacts {
  result: Result;
  accepted: boolean;
  independent: boolean;
  failure_tag: string;
  explanation_score?: number;
}

const OUTCOMES: Array<{ id: Outcome; title: string; detail: string }> = [
  { id: "independent", title: "Independent", detail: "Solved with zero hints and no reference." },
  { id: "assisted", title: "Assisted / slow", detail: "Solved, but with hints, references, or well over the timebox." },
  { id: "solution", title: "Needed solution", detail: "Could not finish without reading an answer." },
  { id: "skipped", title: "Skipped", detail: "Did not attempt today. No memory penalty." },
];

const BLOCKERS: Array<[string, string]> = [
  ["recognition", "Recognition"],
  ["derivation", "Derivation"],
  ["implementation", "Implementation"],
  ["bugs", "Bug / edge case"],
  ["complexity", "Complexity"],
  ["communication", "Explanation"],
];

export function deriveFacts(
  outcome: Outcome,
  hintsUsed: boolean,
  accepted: boolean,
  blocker: string,
  explanation?: number,
): FinishFacts {
  const result: Result =
    outcome === "independent" ? "green"
    : outcome === "assisted" ? "yellow"
    : outcome === "solution" ? "red"
    : "skipped";
  return {
    result,
    accepted: outcome === "skipped" ? false : accepted,
    independent: outcome === "independent" && !hintsUsed,
    failure_tag: result === "green" ? "none" : result === "skipped" ? "unspecified" : blocker || "unspecified",
    explanation_score: outcome === "skipped" ? undefined : explanation,
  };
}

export function previewLine(facts: FinishFacts, highestHint: string | null, elapsedMinutes: number): string {
  const parts = [
    facts.result,
    facts.independent ? "independent" : "assisted",
    highestHint || "H0",
  ];
  if (facts.accepted) parts.push("accepted");
  if (facts.failure_tag !== "none" && facts.failure_tag !== "unspecified") parts.push(`blocker: ${facts.failure_tag}`);
  if (facts.explanation_score != null) parts.push(`explains ${facts.explanation_score}/5`);
  parts.push(`${elapsedMinutes} min`);
  return `Records: ${parts.join(" · ")}`;
}

interface Props {
  origin: "scheduled" | "ad_hoc";
  hintsUsed: boolean;
  highestHint: string | null;
  elapsedMinutes: number;
  elapsedCapped?: boolean;
  busy: boolean;
  error: string;
  onSubmit: (facts: FinishFacts) => void;
  onAbandon?: () => void;
  onClose: () => void;
}

export function FinishSheet({ origin, hintsUsed, highestHint, elapsedMinutes, elapsedCapped = false, busy, error, onSubmit, onAbandon, onClose }: Props) {
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [accepted, setAccepted] = useState(false);
  const [blocker, setBlocker] = useState("");
  const [explanation, setExplanation] = useState<number | undefined>();
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose);
  const busyRef = useRef(busy);
  closeRef.current = onClose;
  busyRef.current = busy;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const focusable = () => Array.from(dialog.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
    ));
    focusable()[0]?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busyRef.current) {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusable();
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  const blockerRequired = outcome === "assisted" || outcome === "solution";
  const facts = useMemo(
    () => (outcome ? deriveFacts(outcome, hintsUsed, accepted, blocker, explanation) : null),
    [outcome, hintsUsed, accepted, blocker, explanation],
  );
  const ready = Boolean(outcome) && (!blockerRequired || Boolean(blocker));

  return (
    <div className="finish-scrim" role="presentation" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
      <section ref={dialogRef} className="finish-sheet" role="dialog" aria-modal="true" aria-label="Record attempt">
        <header className="finish-head">
          <h2>Close the attempt</h2>
          <button className="finish-close" onClick={onClose} aria-label="Close without recording">✕</button>
        </header>

        <fieldset className="outcome-choice">
          <legend>Outcome — pick one</legend>
          {OUTCOMES.map(option => {
            const disabled = option.id === "independent" && hintsUsed;
            return (
              <label key={option.id} className={`outcome-option ${outcome === option.id ? "selected" : ""} ${disabled ? "disabled" : ""}`}>
                <input
                  type="radio"
                  name="outcome"
                  value={option.id}
                  checked={outcome === option.id}
                  disabled={disabled || busy}
                  onChange={() => setOutcome(option.id)}
                />
                <span className="outcome-title">{option.title}</span>
                <span className="outcome-detail">{disabled ? `Hints used through ${highestHint} — this attempt records as assisted.` : option.detail}</span>
              </label>
            );
          })}
        </fieldset>

        {outcome && outcome !== "skipped" && (
          <div className="finish-facts">
            <label className="fact-check">
              <input type="checkbox" checked={accepted} disabled={busy} onChange={event => setAccepted(event.target.checked)} />
              Accepted by LeetCode
            </label>
            <label className={`fact-select ${blockerRequired && !blocker ? "required" : ""}`}>
              <span>Primary blocker{blockerRequired ? " (required)" : ""}</span>
              <select value={blocker} disabled={busy} onChange={event => setBlocker(event.target.value)}>
                <option value="">{blockerRequired ? "Choose the blocker…" : "None"}</option>
                {BLOCKERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            <label className="fact-select">
              <span>Explanation quality (optional)</span>
              <select value={explanation ?? ""} disabled={busy} onChange={event => setExplanation(event.target.value ? Number(event.target.value) : undefined)}>
                <option value="">Not rated</option>
                <option value="1">1 — could not explain</option>
                <option value="2">2 — fragmented</option>
                <option value="3">3 — adequate</option>
                <option value="4">4 — clear</option>
                <option value="5">5 — interview-ready</option>
              </select>
            </label>
          </div>
        )}

        {facts && <p className="finish-preview" data-testid="finish-preview">
          {previewLine(facts, highestHint, elapsedMinutes)}{elapsedCapped ? " · duration capped at API maximum" : ""}
        </p>}
        {error && <p className="form-message" role="status">{error}</p>}

        <footer className="finish-foot">
          {origin === "ad_hoc" && onAbandon && (
            <button className="abandon-link" disabled={busy} onClick={onAbandon}>Abandon — record nothing</button>
          )}
          <button
            className="button primary finish-submit"
            disabled={!ready || busy}
            onClick={() => facts && onSubmit(facts)}
          >
            Record attempt
          </button>
        </footer>
      </section>
    </div>
  );
}
