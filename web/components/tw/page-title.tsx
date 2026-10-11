/** Big page title for workspace pages (iac style): title, one-line description, actions. */
export function PageTitle({ title, description, children }: { title: string; description?: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div className="flex items-start gap-4">
      <div className="min-w-0 flex-1">
        <h1 className="text-[26px] font-medium tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-[14px] text-muted-foreground">{description}</p>}
      </div>
      {children}
    </div>
  );
}

export function PageBody({ children }: { children: React.ReactNode }) {
  return <div className="flex-1 overflow-y-auto"><div className="mx-auto flex max-w-[1040px] flex-col gap-8 px-8 py-10">{children}</div></div>;
}
