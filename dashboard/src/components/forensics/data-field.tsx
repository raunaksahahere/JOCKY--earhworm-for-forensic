import { cn } from "@/lib/utils";

export function DataField({
  label,
  value,
  mono = false,
  wrap = false,
  className,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
  wrap?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <p className="text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p
        className={cn(
          "mt-1 text-sm text-foreground",
          mono && "font-mono text-[13px]",
          wrap ? "break-all" : "truncate",
        )}
      >
        {value}
      </p>
    </div>
  );
}

export function DataGrid({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3", className)}>
      {children}
    </div>
  );
}
