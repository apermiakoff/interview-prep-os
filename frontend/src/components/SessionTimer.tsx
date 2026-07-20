import { useEffect, useRef, useState } from "react";

export function SessionTimer({ minutes = 35, onElapsed }: { minutes?: number; onElapsed?: (minutes: number) => void }) {
  const total = minutes * 60;
  const [remaining, setRemaining] = useState(total);
  const [running, setRunning] = useState(false);
  const deadline = useRef<number | null>(null);

  useEffect(() => {
    if (!running) return;
    const update = () => {
      const next = Math.max(0, Math.ceil(((deadline.current || Date.now()) - Date.now()) / 1000));
      setRemaining(next);
      onElapsed?.(Math.floor((total - next) / 60));
      if (next === 0) setRunning(false);
    };
    const id = window.setInterval(update, 250);
    update();
    return () => window.clearInterval(id);
  }, [running, total, onElapsed]);

  const start = () => {
    deadline.current = Date.now() + remaining * 1000;
    setRunning(true);
  };
  const pause = () => {
    if (deadline.current) setRemaining(Math.max(0, Math.ceil((deadline.current - Date.now()) / 1000)));
    setRunning(false);
  };
  const reset = () => {
    setRunning(false);
    deadline.current = null;
    setRemaining(total);
    onElapsed?.(0);
  };
  const label = `${String(Math.floor(remaining / 60)).padStart(2, "0")}:${String(remaining % 60).padStart(2, "0")}`;
  const progress = 360 * (1 - remaining / total);

  return (
    <section className="timer" aria-label="Interview timebox">
      <div className="timer-ring" style={{ "--progress": `${progress}deg` } as React.CSSProperties}>
        <strong>{label}</strong>
        <span role="status">{remaining === 0 ? "complete" : running ? "in session" : remaining === total ? "ready" : "paused"}</span>
      </div>
      <div className="timer-actions">
        <button className="button primary" onClick={start} disabled={running || remaining === 0}>{remaining < total ? "Resume" : "Start session"}</button>
        <button className="button subtle" onClick={pause} disabled={!running}>Pause</button>
        <button className="button subtle" onClick={reset}>Reset</button>
      </div>
    </section>
  );
}
