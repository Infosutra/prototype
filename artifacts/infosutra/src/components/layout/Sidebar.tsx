import { Link, useLocation } from "wouter";
import {
  BarChart3,
  Database,
  FolderGit2,
  Settings,
  BrainCircuit,
  FileText,
  MessageSquare,
  Activity,
  RefreshCw,
  ShieldAlert,
  Library,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useGetProjects, useGetSettings } from "@workspace/api-client-react";
import { useStudy } from "@/components/study/StudyProvider";

const navigation = [
  { name: "Dashboard", href: "/", icon: Activity },
  { name: "Studies", href: "/studies", icon: Library },
  { name: "Forms", href: "/forms", icon: FolderGit2 },
  { name: "Data Quality", href: "/dqa", icon: ShieldAlert },
  { name: "Data Explorer", href: "/data", icon: Database },
  { name: "Analytics", href: "/analytics", icon: BarChart3 },
  { name: "AI Insights", href: "/ai", icon: BrainCircuit },
  { name: "Prompts", href: "/prompts", icon: MessageSquare },
  { name: "Reports", href: "/reports", icon: FileText },
  { name: "Settings", href: "/settings", icon: Settings },
];

type SidebarNavProps = {
  onNavigate?: () => void;
  className?: string;
};

export function SidebarNav({ onNavigate, className }: SidebarNavProps) {
  const [location] = useLocation();
  const settings = useGetSettings();
  const projects = useGetProjects();
  const { studies, activeStudy, activeStudyId, setActiveStudyId } = useStudy();
  const isConnected = settings.data?.kobo.connected ?? false;
  const latestSync = (projects.data ?? [])
    .map((project) => project.lastSyncAt)
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1);

  return (
    <div
      className={cn(
        "flex flex-col w-full max-w-xs bg-sidebar text-sidebar-foreground h-full border-r border-sidebar-border relative z-10",
        className,
      )}
    >
      <div className="flex h-14 items-center px-4 border-b border-sidebar-border">
        <Database className="w-6 h-6 text-primary mr-2 shrink-0" />
        <span className="font-bold text-lg tracking-tight">Infosutra</span>
      </div>

      <div className="px-3 py-3 border-b border-sidebar-border space-y-1.5">
        <label className="text-[10px] uppercase tracking-wider text-sidebar-foreground/50 px-1">
          Study workspace
        </label>
        <select
          className="w-full h-9 rounded-md border border-sidebar-border bg-sidebar-accent/40 px-2 text-sm"
          value={activeStudyId ?? ""}
          onChange={(e) => setActiveStudyId(e.target.value || null)}
        >
          {studies.length === 0 && <option value="">No studies yet</option>}
          {studies.map((study) => (
            <option key={study.id} value={study.id}>
              {study.name}
              {study.dayNumber != null ? ` · Day ${study.dayNumber}` : ""}
            </option>
          ))}
        </select>
        {activeStudy ? (
          <p className="px-1 text-[11px] text-sidebar-foreground/50 truncate">
            {activeStudy.projectCount} forms ·{" "}
            {activeStudy.submissionCount.toLocaleString()} submissions
          </p>
        ) : (
          <p className="px-1 text-[11px] text-sidebar-foreground/50">
            Create a study to start collecting and analysing forms
          </p>
        )}
      </div>

      <div className="flex-1 overflow-y-auto py-4">
        <nav className="space-y-1 px-2">
          {navigation.map((item) => {
            const isActive =
              location === item.href || (item.href !== "/" && location.startsWith(item.href));
            return (
              <Link
                key={item.name}
                href={item.href}
                onClick={() => onNavigate?.()}
                className={cn(
                  "group flex items-center px-3 py-2.5 text-sm font-medium rounded-md transition-colors",
                  isActive
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
                )}
                data-testid={`nav-${item.name.toLowerCase().replace(/\s+/g, "-")}`}
              >
                <item.icon
                  className={cn(
                    "mr-3 flex-shrink-0 h-5 w-5",
                    isActive
                      ? "text-primary"
                      : "text-sidebar-foreground/50 group-hover:text-sidebar-foreground/70",
                  )}
                  aria-hidden="true"
                />
                {item.name}
              </Link>
            );
          })}
        </nav>
      </div>

      <div className="p-4 border-t border-sidebar-border bg-sidebar/50">
        <div className="flex items-center text-xs text-sidebar-foreground/60">
          <div
            className={cn(
              "w-2 h-2 rounded-full mr-2 shrink-0",
              isConnected ? "bg-green-500" : "bg-muted-foreground",
            )}
          />
          <span>KoboToolbox {isConnected ? "Connected" : "Not connected"}</span>
        </div>
        <div className="mt-2 flex items-center text-xs text-sidebar-foreground/50">
          <RefreshCw className="w-3 h-3 mr-1 shrink-0" />
          <span className="truncate">
            Last sync: {latestSync ? new Date(latestSync).toLocaleString() : "Never"}
          </span>
        </div>
      </div>
    </div>
  );
}

export function Sidebar() {
  return <SidebarNav className="w-64" />;
}
