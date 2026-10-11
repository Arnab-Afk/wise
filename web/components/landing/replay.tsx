"use client";

import { useEffect, useState } from "react";

// Incident #53 from our test runs, as it happened (times are real; descriptions shortened).
type Tone = "alert" | "look" | "act" | "ok";
const STEPS: { t: number; tone: Tone; text: string; detail?: string }[] = [
  { t: 0, tone: "alert", text: "checkout is failing 19% of requests", detail: "gateway errors rising too" },
  { t: 4, tone: "look", text: "Seen before: the same gift-wrap bug, 3 times" },
  { t: 4, tone: "look", text: "Deploy bf60a94 went out 2 seconds before the errors" },
  { t: 8, tone: "look", text: "TypeError at pricing.py:8 on orders without gift wrap", detail: "97% confidence" },
  { t: 9, tone: "act", text: "Rolled back checkout to 5455ae3" },
  { t: 70, tone: "ok", text: "checkout and gateway back to 0% errors" },
  { t: 115, tone: "act", text: "Claude wrote a fix and 4 regression tests", detail: "6 of 6 tests pass" },
  { t: 118, tone: "act", text: "Deployed the fix, kept the feature" },
  { t: 179, tone: "ok", text: "Healthy for 60 seconds" },
];
const END = 189;

const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const wall = (s: number) => {
  const total = 3 * 3600 + 7 * 60 + s; // paged at 3:07:00 a.m.
  return `${Math.floor(total / 3600)}:${String(Math.floor((total % 3600) / 60)).padStart(2, "0")}:${String(Math.floor(total % 60)).padStart(2, "0")} a.m.`;
};

/** The hero: a real incident replaying itself, from the page to the fix. */
export function Replay() {
  const [shown, setShown] = useState(0);
  const [done, setDone] = useState(false);
  const [now, setNow] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const timers: ReturnType<typeof setTimeout>[] = [];
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      // No replay: show the finished timeline.
      timers.push(setTimeout(() => { setShown(STEPS.length); setDone(true); setNow(END); }, 0));
      return () => timers.forEach(clearTimeout);
    }
    const run = () => {
      setShown(0); setDone(false); setNow(0);
      let at = 900;
      STEPS.forEach((s, i) => {
        const gap = i === 0 ? 0 : Math.min(1500, 450 + (s.t - STEPS[i - 1].t) * 14);
        at += gap;
        timers.push(setTimeout(() => { if (!cancelled) { setShown(i + 1); setNow(s.t); } }, at));
      });
      timers.push(setTimeout(() => { if (!cancelled) { setDone(true); setNow(END); } }, at + 1100));
      timers.push(setTimeout(() => { if (!cancelled) run(); }, at + 9000));
    };
    run();
    return () => { cancelled = true; timers.forEach(clearTimeout); };
  }, []);

  return (
    <figure className="lp-replay" aria-label="A real incident, replayed: checkout broke and Tracewise fixed it in 3 minutes 9 seconds">
      <header className="lp-replay-head">
        <span className={`lp-dot ${done ? "is-ok" : "is-alert"}`} />
        <span className="lp-replay-title">Incident #53, checkout</span>
        <span className="lp-replay-clock">{wall(now)}</span>
      </header>
      <ol className="lp-steps">
        {STEPS.slice(0, shown).map((s, i) => (
          <li key={i} className={`lp-step is-${s.tone}`}>
            <span className="lp-step-t">+{clock(s.t)}</span>
            <span className="lp-step-text">{s.text}{s.detail && <span className="lp-step-detail">{s.detail}</span>}</span>
          </li>
        ))}
      </ol>
      <div className={`lp-outcome ${done ? "is-in" : ""}`} aria-hidden={!done}>
        <p className="lp-outcome-title">Resolved in 3m 09s while everyone slept</p>
        <p className="lp-outcome-body">Root cause, evidence and the fix are written up. Agent cost: $0.15.</p>
      </div>
    </figure>
  );
}
