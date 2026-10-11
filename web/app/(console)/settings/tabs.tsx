"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const TABS = [["/settings/workspace", "Workspace"], ["/settings/profile", "Profile"], ["/settings/emails", "Email log"]];

export function SettingsTabs() {
  const path = usePathname();
  return (
    <div className="flex h-8 items-center rounded-lg border p-0.5">
      {TABS.map(([href, label]) => (
        <Link key={href} href={href} className={cn("flex h-full items-center rounded-md px-3 text-[13px] text-muted-foreground",
          path === href && "bg-muted text-foreground")}>{label}</Link>
      ))}
    </div>
  );
}
