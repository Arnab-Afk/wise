import { Logo } from "@/components/tw/brand";

export default function AuthLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex min-h-dvh flex-col bg-sidebar">
      <header className="flex items-center gap-2.5 px-6 pt-6">
        <Logo size={26} />
        <span className="font-mono text-[14px]">tracewise</span>
      </header>
      <main className="flex flex-1 items-center justify-center px-4 py-10">{children}</main>
      <footer className="pb-6 text-center text-[12px] text-muted-foreground">
        The on-call agent that fixes production and shows its work.
      </footer>
    </div>
  );
}
