"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

// A slow-drifting field of log and trace characters (after iac's HCL field). A few cells are
// incidents: they flare red, then heal to green, the way the agent closes them.

const CELL_W = 9;
const CELL_H = 15;
const FPS = 14;
const QUIET = "·";
const MID = ":-=~.";
const LOUD = "#|/\\<>";

function hash(c: number, r: number) {
  const h = Math.sin(c * 127.1 + r * 311.7) * 43758.5453;
  return h - Math.floor(h);
}

function field(c: number, r: number, t: number) {
  const x = c * 0.075;
  const y = r * 0.22;
  const v = Math.sin(x * 1.3 + t * 0.5) * Math.sin(y * 0.9 - t * 0.35)
    + Math.sin((x + y) * 0.7 + t * 0.25) * 0.6 + Math.sin(x * 0.31 - t * 0.15) * 0.5;
  return (v + 2.1) / 4.2;
}

export function GlyphField({ className }: { className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const mono = getComputedStyle(document.documentElement).getPropertyValue("--font-geist-mono").trim() || "monospace";
    let cols = 0, rows = 0;
    let nodes: { c: number; r: number; phase: number }[] = [];

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const { width, height } = canvas.getBoundingClientRect();
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.font = `11px ${mono}`;
      ctx.textBaseline = "top";
      cols = Math.ceil(width / CELL_W);
      rows = Math.ceil(height / CELL_H);
      nodes = Array.from({ length: Math.max(4, Math.round(cols / 16)) }, (_, i) => ({
        c: Math.floor(hash(i, 7) * cols), r: Math.floor(hash(i, 13) * rows), phase: hash(i, 29) * Math.PI * 2,
      }));
    };

    const draw = (t: number) => {
      const { width, height } = canvas.getBoundingClientRect();
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = "#f4f4f2";
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          const v = field(c, r, t);
          const h = hash(c, r);
          let ch: string;
          if (v > 0.66) { ch = LOUD[Math.floor(h * LOUD.length)]; ctx.globalAlpha = 0.5 + (v - 0.66) * 1.2; }
          else if (v > 0.48) { ch = MID[Math.floor(h * MID.length)]; ctx.globalAlpha = 0.26; }
          else { if (h > 0.55) continue; ch = QUIET; ctx.globalAlpha = 0.14; }
          ctx.fillText(ch, c * CELL_W, r * CELL_H);
        }
      }
      for (const n of nodes) {
        // 0..1 through each incident's life: opens red, the agent works, it heals green, fades.
        const life = ((t * 0.12 + n.phase / (Math.PI * 2)) % 1 + 1) % 1;
        const healed = life > 0.55;
        ctx.fillStyle = healed ? "#5fd08a" : "#f0605a";
        ctx.globalAlpha = healed ? Math.max(0, 1 - (life - 0.55) / 0.45) : 0.35 + 0.65 * Math.abs(Math.sin(t * 3 + n.phase));
        ctx.clearRect(n.c * CELL_W - 1, n.r * CELL_H, CELL_W + 2, CELL_H);
        ctx.fillText("■", n.c * CELL_W, n.r * CELL_H);
      }
      ctx.globalAlpha = 1;
    };

    resize();
    draw(0);
    if (reduced) {
      const ro = new ResizeObserver(() => { resize(); draw(0); });
      ro.observe(canvas);
      return () => ro.disconnect();
    }
    let raf = 0, last = 0, visible = true;
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      if (!visible || now - last < 1000 / FPS) return;
      last = now;
      draw(now / 1000);
    };
    raf = requestAnimationFrame(tick);
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    const io = new IntersectionObserver(([e]) => (visible = e.isIntersecting));
    io.observe(canvas);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); io.disconnect(); };
  }, []);

  return <canvas ref={ref} aria-hidden className={cn("block h-full w-full", className)} />;
}
