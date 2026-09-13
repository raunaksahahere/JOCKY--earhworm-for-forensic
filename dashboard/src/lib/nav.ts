import {
  LayoutDashboard,
  TerminalSquare,
  FolderSearch,
  FileText,
  History,
  Wrench,
  ActivitySquare,
  SlidersHorizontal,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  label: string;
  to: string;
  icon: LucideIcon;
  description: string;
}

export const NAV_ITEMS: NavItem[] = [
  { label: "Overview", to: "/", icon: LayoutDashboard, description: "Operations dashboard" },
  {
    label: "Command Center",
    to: "/command-center",
    icon: TerminalSquare,
    description: "Run JOCKY commands",
  },
  {
    label: "Investigation Workspace",
    to: "/workspace",
    icon: FolderSearch,
    description: "Cases & evidence",
  },
  { label: "Reports", to: "/reports", icon: FileText, description: "Forensic report archive" },
  { label: "History", to: "/history", icon: History, description: "Command execution log" },
  { label: "Tools", to: "/tools", icon: Wrench, description: "Analysis tool launcher" },
  {
    label: "System Status",
    to: "/system",
    icon: ActivitySquare,
    description: "Host & engine monitoring",
  },
  { label: "Settings", to: "/settings", icon: SlidersHorizontal, description: "API & preferences" },
];
