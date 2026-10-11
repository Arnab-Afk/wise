"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Activity, Bot, Cable, Check, ChevronsUpDown, GitCommitHorizontal, LogOut, Plus, Settings, Siren, Wrench } from "lucide-react";
import { canAdmin, useMe } from "@/hooks/use-me";
import { api, ACTIVE, switchTo, type Incident } from "@/lib/api";
import { usePoll, useStream } from "@/hooks/use-stream";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/incidents", label: "incidents", icon: Siren },
  { href: "/services", label: "services", icon: Activity },
  { href: "/deploys", label: "deploys", icon: GitCommitHorizontal },
  { href: "/fixes", label: "fixes", icon: Wrench },
  { href: "/sources", label: "sources", icon: Cable },
  { href: "/agents", label: "coding agents", icon: Bot },
  { href: "/settings/project", label: "settings", icon: Settings },
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

export function WorkspaceBadge() {
  const me = useMe();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  const ws = me?.workspace;
  return (
    <div ref={box} className="relative">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2.5 rounded-lg px-1 py-1 text-left hover:bg-black/[0.04]">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-foreground font-mono text-[13px] font-semibold text-background">
          {(ws?.name ?? "T").slice(0, 1).toUpperCase()}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[12px] text-muted-foreground">{ws?.name ?? "tracewise"}</span>
          <span className="block truncate font-mono text-[13px]">{me?.project?.slug ?? "—"}</span>
        </span>
        <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" />
      </button>
      {open && me && (
        <div className="absolute top-full right-0 left-0 z-50 mt-1 rounded-xl border bg-background p-1.5 shadow-lg">
          <p className="micro px-2 pt-1 pb-1.5">projects in {ws?.name}</p>
          {me.projects.map((p) => (
            <button key={p.id} onClick={() => switchTo(ws?.id ?? null, p.id)}
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] hover:bg-muted">
              <span className="min-w-0 flex-1 truncate font-mono">{p.slug}</span>
              {p.id === me.project?.id && <Check className="size-3.5" />}
            </button>
          ))}
          {canAdmin(me) && (
            <Link href="/settings/project#new" onClick={() => setOpen(false)}
              className="flex items-center gap-2 rounded-md px-2 py-1.5 text-[13px] text-muted-foreground hover:bg-muted hover:text-foreground">
              <Plus className="size-3.5" />New project
            </Link>
          )}
          {me.workspaces.length > 1 && (
            <>
              <div className="my-1.5 border-t" />
              <p className="micro px-2 pt-0.5 pb-1.5">workspaces</p>
              {me.workspaces.map((w) => (
                <button key={w.id} onClick={() => switchTo(w.id, null)}
                  className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] hover:bg-muted">
                  <span className="min-w-0 flex-1 truncate">{w.name}</span>
                  <span className="text-[11px] text-muted-foreground">{w.role}</span>
                  {w.id === ws?.id && <Check className="size-3.5" />}
                </button>
              ))}
            </>
          )}
          <div className="my-1.5 border-t" />
          <Link href="/onboarding?new=1" className="flex items-center gap-2 rounded-md px-2 py-1.5 text-[13px] text-muted-foreground hover:bg-muted hover:text-foreground">
            <Plus className="size-3.5" />New workspace
          </Link>
        </div>
      )}
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
