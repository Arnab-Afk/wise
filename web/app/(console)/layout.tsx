import { Suspense } from "react";
import { LiveActivity, NavFallback, SidebarNav, UserChip, WorkspaceBadge } from "@/components/tw/sidebar";

export default function ConsoleLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex h-dvh overflow-hidden">
      <aside className="flex w-[232px] shrink-0 flex-col gap-5 bg-sidebar px-3 pt-4 pb-3">
        <WorkspaceBadge />
        <Suspense fallback={<NavFallback />}>
          <SidebarNav />
        </Suspense>
        <div className="mt-auto flex flex-col gap-1 border-t pt-3">
          <LiveActivity />
          <UserChip />
        </div>
      </aside>
      <main className="my-2 mr-2 flex min-w-0 flex-1 flex-col overflow-hidden rounded-xl border bg-background shadow-[0_1px_2px_rgba(0,0,0,0.03)]">
        {children}
      </main>
    </div>
  );
}
