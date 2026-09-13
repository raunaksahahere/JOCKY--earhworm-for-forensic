import { Menu } from "lucide-react";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { SidebarNav } from "@/components/layout/sidebar-nav";
import { StatusPill } from "@/components/layout/status-pill";
import { useJockyStore } from "@/lib/store";

export function TopBar({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string | undefined;
  actions?: React.ReactNode;
}) {
  const { apiConnected } = useJockyStore();

  return (
    <header className="surface-glass sticky top-0 z-20 flex items-center gap-3 border-b border-border px-4 py-3.5 sm:px-6">
      <Sheet>
        <SheetTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="shrink-0 lg:hidden"
            aria-label="Open navigation"
          >
            <Menu className="h-5 w-5" />
          </Button>
        </SheetTrigger>
        <SheetContent side="left" className="w-72 border-border bg-sidebar p-0">
          <SidebarNav />
        </SheetContent>
      </Sheet>

      <div className="min-w-0 flex-1">
        <h1 className="truncate text-[15px] font-semibold tracking-tight text-foreground">
          {title}
        </h1>
        {description && <p className="truncate text-xs text-muted-foreground">{description}</p>}
      </div>

      <div className="hidden items-center gap-2 sm:flex">
        <StatusPill
          tone={apiConnected === null ? "muted" : apiConnected ? "success" : "critical"}
          label={apiConnected === null ? "CHECKING" : apiConnected ? "API ONLINE" : "API OFFLINE"}
          pulse={apiConnected === true}
        />
      </div>

      {actions}
    </header>
  );
}
