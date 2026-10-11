"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Activity, Bot, Cable, GitCommitHorizontal, LogOut, PanelLeft, Settings, Siren, Wrench } from "lucide-react";
import { useMe } from "@/hooks/use-me";
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
  { href: "/settings/workspace", label: "settings", icon: Settings },
];

export function SidebarNav() {
  const pathname = usePathname();
  return (
    <nav className="flex flex-col gap-0.5">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`)
          || (href.startsWith("/settings") && pathname.startsWith("/settings"));
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
  const me = useMe();
  return (
    <div className="flex items-center gap-2.5 px-1">
      <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-foreground font-mono text-[13px] font-semibold text-background">
        {(me?.workspace?.name ?? "T").slice(0, 1).toUpperCase()}
      </span>
      <span className="truncate font-mono text-[13px]">{me?.workspace?.slug ?? "tracewise"}</span>
      <button onClick={onToggle} className="ml-auto rounded-md p-1 text-muted-foreground hover:bg-black/[0.04]" aria-label="Collapse sidebar">
        <PanelLeft className="size-4 stroke-[1.6]" />
      </button>
    </div>
  );
}

/** Who's signed in, with a way out. */
export function UserChip() {
  const me = useMe();
  if (!me) return <div className="h-10" />;
  const label = me.name || me.email;
  return (
    <div className="flex items-center gap-2 rounded-lg px-1.5 py-1">
      <Link href="/settings/profile" className="flex min-w-0 flex-1 items-center gap-2.5 rounded-md hover:opacity-80">
        {me.avatar_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={me.avatar_url} alt="" className="size-7 rounded-full" />
        ) : (
          <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-[12px] font-medium">
            {label.slice(0, 1).toUpperCase()}
          </span>
        )}
        <span className="min-w-0">
          <span className="block truncate text-[13px]">{label}</span>
          <span className="block truncate text-[11.5px] text-muted-foreground">{me.role ?? "no workspace"}</span>
        </span>
      </Link>
      <form action="/api/auth/logout" method="post">
        <button type="submit" className="rounded-md p-1.5 text-muted-foreground hover:bg-black/[0.04] hover:text-foreground" aria-label="Sign out" title="Sign out">
          <LogOut className="size-4" />
        </button>
      </form>
    </div>
  );
}
