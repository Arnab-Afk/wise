import { Suspense } from "react";
import { LiveActivity, NavFallback, SidebarNav, UserChip, WorkspaceBadge } from "@/components/tw/sidebar";

export default function ConsoleLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex h-dvh gap-2 overflow-hidden bg-sidebar p-2">
      <aside className="flex w-[240px] shrink-0 flex-col gap-4 overflow-y-auto rounded-xl border bg-background px-3 pt-3 pb-3 shadow-[0_1px_2px_rgba(0,0,0,0.03)]">
        <WorkspaceBadge />
        <Suspense fallback={<NavFallback />}>
          <SidebarNav />
        </Suspense>
        <div className="mt-auto flex flex-col gap-1 border-t pt-3">
          <LiveActivity />
          <UserChip />
        </div>
      </aside>
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-xl border bg-background shadow-[0_1px_2px_rgba(0,0,0,0.03)]">
        {children}
      </main>
    </div>
  );
}
