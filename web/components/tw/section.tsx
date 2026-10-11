export function Section({ title, description, action, children }: {
  title: string; description?: string; action?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border">
      <div className="flex items-start gap-3 border-b px-5 py-3.5">
        <div className="min-w-0 flex-1">
          <h2 className="font-medium">{title}</h2>
          {description && <p className="mt-0.5 text-[12.5px] text-muted-foreground">{description}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
