import { cn } from "@/lib/utils";

export function PageHeader({ icon: Icon, title, children, className }: {
  icon?: React.ComponentType<{ className?: string }>; title: React.ReactNode; children?: React.ReactNode; className?: string;
}) {
  return (
    <header className={cn("flex h-14 shrink-0 items-center gap-3 border-b px-5", className)}>
      {Icon && <Icon className="size-[18px] stroke-[1.6] text-foreground/80" />}
      <h1 className="truncate text-[15px] font-medium tracking-tight">{title}</h1>
      <div className="ml-auto flex items-center gap-2">{children}</div>
    </header>
  );
}

export function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1.5 py-20 text-center">
      <p className="font-medium">{title}</p>
      {children && <p className="max-w-sm text-muted-foreground">{children}</p>}
    </div>
  );
}
