import { cn } from "@/lib/utils";

type Tone = "ok" | "warn" | "bad" | "info" | "neutral" | "dark";

const TONES: Record<Tone, string> = {
  ok: "bg-ok-soft text-ok",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
  info: "bg-info-soft text-info",
  neutral: "bg-muted text-muted-foreground",
  dark: "bg-foreground text-background",
};

export function Pill({ tone = "neutral", className, children, dot }: {
  tone?: Tone; className?: string; children: React.ReactNode; dot?: boolean;
}) {
  return (
    <span className={cn("inline-flex h-5 shrink-0 items-center gap-1.5 rounded-md px-1.5 text-[11.5px] font-medium whitespace-nowrap",
      TONES[tone], className)}>
      {dot && <span className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

/** A quiet outlined chip, like neatlogs' "Chain" / "Tool" tags. */
export function Tag({ children, className, mono }: { children: React.ReactNode; className?: string; mono?: boolean }) {
  return (
    <span className={cn("inline-flex h-5 shrink-0 items-center gap-1 rounded-md border bg-background px-1.5 text-[11.5px] text-muted-foreground",
      mono && "font-mono text-[11px]", className)}>
      {children}
    </span>
  );
}

const STATUS: Record<string, { tone: Tone; label: string; live?: boolean }> = {
  open: { tone: "bad", label: "Open", live: true },
  investigating: { tone: "info", label: "Investigating", live: true },
  acting: { tone: "warn", label: "Acting", live: true },
  fixing: { tone: "warn", label: "Fixing", live: true },
  verifying: { tone: "info", label: "Verifying", live: true },
  resolved: { tone: "ok", label: "Resolved" },
  escalated: { tone: "neutral", label: "Escalated" },
};

export function StatusPill({ status }: { status: string }) {
  const s = STATUS[status] ?? { tone: "neutral" as Tone, label: status };
  return (
    <Pill tone={s.tone}>
      {s.live && (
        <span className="relative flex size-1.5">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-current opacity-60" />
          <span className="relative inline-flex size-1.5 rounded-full bg-current" />
        </span>
      )}
      {s.label}
    </Pill>
  );
}

const HEALTH: Record<string, Tone> = { healthy: "ok", erroring: "bad", slow: "warn", silent: "neutral",
  alerting: "bad", "logging errors": "bad" };

export function HealthPill({ status }: { status: string }) {
  return <Pill tone={HEALTH[status] ?? "neutral"} dot>{status}</Pill>;
}

/** Signal-strength bars for severity, like neatlogs' fixes list. */
export function SeverityBars({ severity }: { severity: string }) {
  const level = { critical: 3, high: 2, medium: 1, low: 1 }[severity] ?? 1;
  const color = level === 3 ? "bg-bad" : level === 2 ? "bg-warn" : "bg-muted-foreground/50";
  return (
    <span className="inline-flex h-3.5 items-end gap-[2px]" title={`${severity} severity`}>
      {[1, 2, 3].map((i) => (
        <span key={i} className={cn("w-[3px] rounded-[1px]", i <= level ? color : "bg-border")}
          style={{ height: `${4 + i * 3}px` }} />
      ))}
    </span>
  );
}

/** Small circular score, like neatlogs' confidence rings. */
export function Ring({ value, size = 34, tone = "ok" }: { value: number; size?: number; tone?: Tone }) {
  const r = (size - 5) / 2;
  const c = 2 * Math.PI * r;
  const stroke = { ok: "var(--ok)", warn: "var(--warn)", bad: "var(--bad)", info: "var(--info)",
    neutral: "var(--muted-foreground)", dark: "var(--foreground)" }[tone];
  return (
    <span className="relative inline-flex shrink-0 items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--border)" strokeWidth={3} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={stroke} strokeWidth={3} strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - Math.max(0, Math.min(1, value / 100)))} />
      </svg>
      <span className="num absolute text-[10.5px] font-semibold">{Math.round(value)}</span>
    </span>
  );
}
