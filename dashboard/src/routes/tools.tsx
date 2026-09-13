import { createFileRoute, Link } from "@tanstack/react-router";
import {
  Cpu,
  FileDigit,
  FileSearch,
  FolderTree,
  Lock,
  ScrollText,
  ServerCog,
  type LucideIcon,
} from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useJockyStore } from "@/lib/store";

export const Route = createFileRoute("/tools")({
  component: Tools,
  head: () => ({
    meta: [
      { title: "Tools — JOCKY" },
      { name: "description", content: "Launch individual JOCKY forensic analysis tools." },
    ],
  }),
});

interface Tool {
  name: string;
  description: string;
  icon: LucideIcon;
  example: string;
}

const TOOLS: Tool[] = [
  {
    name: "SHA-256 Hashing",
    description:
      "Compute a SHA-256 (or MD5/SHA-1/SHA-512) digest of a file to verify evidence integrity.",
    icon: FileDigit,
    example: "HASH FILE evidence.bin",
  },
  {
    name: "File Analysis",
    description:
      "Hash a target file and surface static, informational indicators for analyst review.",
    icon: FileDigit,
    example: "HASH FILE sample.docx",
  },
  {
    name: "Encryption",
    description:
      "Encrypt an evidence file in place to protect it at rest during a chain-of-custody hold.",
    icon: Lock,
    example: "ENCRYPT FILE evidence.bin",
  },
  {
    name: "System Information",
    description: "Collect read-only host details: OS, architecture, CPU, memory, and runtime.",
    icon: ServerCog,
    example: "SYSTEM INFO",
  },
  {
    name: "Process Analysis",
    description: "Observe currently running processes and their resource usage. Read-only.",
    icon: Cpu,
    example: "PROCESSES",
  },
  {
    name: "Directory Analysis",
    description: "List files and folders under a path with size, type, and modification metadata.",
    icon: FolderTree,
    example: "LIST FILES ./evidence",
  },
  {
    name: "File Search",
    description:
      "Search a directory tree for files matching a name to help locate evidence quickly.",
    icon: FileSearch,
    example: "SEARCH FILE malware.exe IN ./samples",
  },
  {
    name: "Report Generator",
    description:
      "Every executed command already produces a structured, timestamped forensic report.",
    icon: ScrollText,
    example: "SYSTEM INFO",
  },
];

function Tools() {
  const { apiConnected } = useJockyStore();

  return (
    <AppShell title="Tools" description="Analysis tool launcher">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {TOOLS.map((tool) => {
          const Icon = tool.icon;
          return (
            <div
              key={tool.name}
              className="flex flex-col justify-between rounded-xl border border-border bg-card p-5 transition-colors hover:border-border-strong"
            >
              <div>
                <div className="flex items-start justify-between">
                  <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-border-strong bg-primary/10 text-primary">
                    <Icon className="h-4.5 w-4.5" strokeWidth={1.75} />
                  </div>
                  <Badge
                    variant="outline"
                    className={
                      apiConnected
                        ? "border-success/30 text-success"
                        : "border-muted-foreground/30 text-muted-foreground"
                    }
                  >
                    {apiConnected ? "Ready" : "Standby"}
                  </Badge>
                </div>
                <h3 className="mt-3 text-sm font-medium text-foreground">{tool.name}</h3>
                <p className="mt-1.5 text-[12px] leading-relaxed text-muted-foreground">
                  {tool.description}
                </p>
              </div>
              <Link to="/command-center" search={{ cmd: tool.example }} className="mt-4">
                <Button variant="outline" size="sm" className="w-full">
                  Launch
                </Button>
              </Link>
            </div>
          );
        })}
      </div>
    </AppShell>
  );
}
