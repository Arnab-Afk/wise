"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Activity, Bot, Cable, GitCommitHorizontal, PanelLeft, Siren, Wrench } from "lucide-react";
import { api, ACTIVE, type Incident } from "@/lib/api";
import { usePoll, useStream } from "@/hooks/use-stream";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/incidents", label: "incidents", icon: Siren },
  { href: "/services", label: "services", icon: Activity },
  { href: "/deploys", label: "deploys", icon: GitCommitHorizontal },
  { href: "/fixes", label: "fixes", icon: Wrench },
  { href: "/sources", label: "sources", icon: Cable },
  { href: "/agents", label: "coding agents", icon: Bot },
];

export function SidebarNav() {
  const pathname = usePathname();
  return (
    <nav className="flex flex-col gap-0.5">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link key={href} href={href}
            className={cn("flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] text-foreground/75 transition-colors hover:bg-black/[0.04] hover:text-foreground",
              active && "bg-black/[0.05] font-medium text-foreground")}>
            <Icon className="size-4 stroke-[1.6]" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

export function NavFallback() {
  return (
    <nav className="flex flex-col gap-0.5">
      {NAV.map(({ href, label, icon: Icon }) => (
        <Link key={href} href={href} className="flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] text-foreground/75">
          <Icon className="size-4 stroke-[1.6]" />
          {label}
        </Link>
      ))}
    </nav>
  );
}

/** Bottom of the sidebar: how many incidents the agent is working on right now. */
export function LiveActivity() {
  const [active, setActive] = useState<number | null>(null);
  const load = () => api<Incident[]>("/v1/incidents?limit=50")
    .then((rows) => setActive(rows.filter((r) => ACTIVE.includes(r.status)).length)).catch(() => {});
  usePoll(load, 10000);
  useStream((e) => { if (e.type === "incident_opened" || e.type === "step") load(); });
  return (
    <Link href="/incidents" className="flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] text-foreground/75 hover:bg-black/[0.04]">
      <span className={cn("size-2 rounded-full", active ? "animate-pulse bg-bad" : "bg-ok")} />
      {active ? "agent working" : "all clear"}
      {active ? <span className="num ml-auto rounded-md bg-bad-soft px-1.5 text-[11px] text-bad">{active}</span> : null}
    </Link>
  );
}

export function WorkspaceBadge({ onToggle }: { onToggle?: () => void }) {
  return (
    <div className="flex items-center gap-2.5 px-1">
      <span className="flex size-7 items-center justify-center rounded-lg bg-foreground font-mono text-[13px] font-semibold text-background">T</span>
      <span className="font-mono text-[13px]">shopfront</span>
      <button onClick={onToggle} className="ml-auto rounded-md p-1 text-muted-foreground hover:bg-black/[0.04]" aria-label="Collapse sidebar">
        <PanelLeft className="size-4 stroke-[1.6]" />
      </button>
    </div>
  );
}
