export function PrintField({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="min-w-0">
      <p className="text-[8.5pt] font-semibold uppercase tracking-wider text-neutral-500">
        {label}
      </p>
      <p className={"mt-0.5 text-[10pt] text-neutral-900 " + (mono ? "font-mono break-all" : "")}>
        {value}
      </p>
    </div>
  );
}

export function PrintSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6 break-inside-avoid">
      <h3 className="mb-2 border-b border-neutral-300 pb-1 text-[9.5pt] font-bold uppercase tracking-widest text-neutral-700">
        {title}
      </h3>
      {children}
    </section>
  );
}
