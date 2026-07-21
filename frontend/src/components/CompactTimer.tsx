import { useEffect, useRef, useState } from "react";

/*
 * Compact command-bar timer. No ring, no dial: a state word, a monospace
 * countdown, and one state-dependent control. Elapsed seconds persist in
 * sessionStorage keyed by session id, so route changes and reloads within the
 * tab never lose the clock. Reaching zero flips the label to OVER and keeps
 * counting — it never auto-submits an attempt.
 */

interface TimerState {
  elapsed: number;
  running: boolean;
  updatedAt: number;
}

const storageKey = (sessionId: string) => `solve-timer:${sessionId}`;

function readState(sessionId: string): TimerState {
  try {
    const raw = sessionStorage.getItem(storageKey(sessionId));
    if (!raw) return { elapsed: 0, running: false, updatedAt: Date.now() };
    const parsed = JSON.parse(raw) as TimerState;
    const drift = parsed.running ? Math.max(0, (Date.now() - parsed.updatedAt) / 1000) : 0;
    return { elapsed: Math.max(0, parsed.elapsed + drift), running: parsed.running, updatedAt: Date.now() };
  } catch {
    return { elapsed: 0, running: false, updatedAt: Date.now() };
  }
}

function writeState(sessionId: string, state: TimerState) {
  try {
    sessionStorage.setItem(storageKey(sessionId), JSON.stringify(state));
  } catch { /* storage may be denied */ }
}

/** Elapsed whole minutes for the attempt record, read at finish time. */
export function readTimerElapsedMinutes(sessionId: string): number {
  return Math.floor(readState(sessionId).elapsed / 60);
}

export function clearTimer(sessionId: string) {
  try { sessionStorage.removeItem(storageKey(sessionId)); } catch { /* ignore */ }
}

function clock(seconds: number) {
  const clamped = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(clamped / 60)).padStart(2, "0")}:${String(clamped % 60).padStart(2, "0")}`;
}

export function CompactTimer({ sessionId, timeboxMinutes }: { sessionId: string; timeboxMinutes: number }) {
  const total = timeboxMinutes * 60;
  const [state, setState] = useState<TimerState>(() => readState(sessionId));
  const [confirmReset, setConfirmReset] = useState(false);
  const anchor = useRef<number>(Date.now() - state.elapsed * 1000);

  useEffect(() => {
    const restored = readState(sessionId);
    anchor.current = Date.now() - restored.elapsed * 1000;
    setState(restored);
    setConfirmReset(false);
  }, [sessionId]);

  useEffect(() => {
    if (!state.running) return;
    const id = window.setInterval(() => {
      setState(current => ({ ...current, elapsed: (Date.now() - anchor.current) / 1000 }));
    }, 1000);
    return () => window.clearInterval(id);
  }, [state.running, sessionId]);

  useEffect(() => {
    writeState(sessionId, { ...state, updatedAt: Date.now() });
  }, [state, sessionId]);

  const start = () => {
    anchor.current = Date.now() - state.elapsed * 1000;
    setState(current => ({ ...current, running: true, updatedAt: Date.now() }));
  };
  const pause = () => setState(current => ({ ...current, running: false, updatedAt: Date.now() }));
  const reset = () => {
    anchor.current = Date.now();
    setState({ elapsed: 0, running: false, updatedAt: Date.now() });
    setConfirmReset(false);
  };

  const remaining = total - state.elapsed;
  const over = remaining <= 0;
  const phase = over ? "over" : state.running ? "live" : state.elapsed > 0 ? "paused" : "ready";
  const display = over ? `+${clock(-remaining)}` : clock(remaining);

  return (
    <div className={`command-timer ${phase}`} role="timer" aria-label="Session timebox">
      <span className="timer-phase">{phase}</span>
      <strong className="timer-clock">{display}</strong>
      {state.running
        ? <button className="timer-control" onClick={pause}>Pause</button>
        : <button className="timer-control" onClick={start}>{state.elapsed > 0 ? "Resume" : "Start"}</button>}
      {state.elapsed > 0 && !state.running && (
        confirmReset
          ? <span className="timer-reset-confirm">Reset? <button onClick={reset}>Yes</button><button onClick={() => setConfirmReset(false)}>No</button></span>
          : <button className="timer-reset" aria-label="Reset timer" title="Reset timer" onClick={() => setConfirmReset(true)}>↺</button>
      )}
    </div>
  );
}
