"use client";

import { useState, useMemo } from "react";
import {
  Search,
  Filter,
  X,
  Bot,
  Activity,
  Cpu,
  Server,
  Download,
} from "lucide-react";

import { AppHeader } from "@/components/app-header";
import { SeverityBadge } from "@/components/status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { useAsync } from "@/hooks/use-async";
import { fetchAuditLog } from "@/lib/api";
import type { AuditLogEntry } from "@/lib/types";

// ── Helpers ──────────────────────────────────────────────────────────

function formatTimestamp(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleString("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

const targetTypeIcons: Record<string, typeof Bot> = {
  agent: Bot,
  session: Activity,
  llm_config: Cpu,
  system: Server,
};

// ── Action group colours ─────────────────────────────────────────────

function actionGroup(action: string): string {
  if (action.startsWith("agent.")) return "agent";
  if (action.startsWith("session.")) return "session";
  if (action.startsWith("ibac.")) return "ibac";
  if (action.startsWith("llm.")) return "llm";
  if (action.startsWith("system.")) return "system";
  return "other";
}

const actionGroupColors: Record<string, string> = {
  agent: "bg-blue-500/10 text-blue-500 border-blue-500/20",
  session: "bg-purple-500/10 text-purple-500 border-purple-500/20",
  ibac: "bg-orange-500/10 text-orange-500 border-orange-500/20",
  llm: "bg-green-500/10 text-green-500 border-green-500/20",
  system: "bg-gray-500/10 text-gray-400 border-gray-500/20",
  other: "bg-gray-500/10 text-gray-400 border-gray-500/20",
};

// ── Main Page ────────────────────────────────────────────────────────

export default function AuditPage() {
  const [search, setSearch] = useState("");
  const [severityFilter, setSeverityFilter] = useState<string>("all");
  const [targetTypeFilter, setTargetTypeFilter] = useState<string>("all");

  const { data: auditLog, loading } = useAsync(() => fetchAuditLog());
  const allLogs = auditLog ?? [];

  const filtered = useMemo(() => {
    return allLogs.filter((log) => {
      const matchesSearch =
        search === "" ||
        log.action.toLowerCase().includes(search.toLowerCase()) ||
        log.actor.toLowerCase().includes(search.toLowerCase()) ||
        log.target.toLowerCase().includes(search.toLowerCase()) ||
        log.details.toLowerCase().includes(search.toLowerCase());

      const matchesSeverity =
        severityFilter === "all" || log.severity === severityFilter;

      const matchesType =
        targetTypeFilter === "all" || log.target_type === targetTypeFilter;

      return matchesSearch && matchesSeverity && matchesType;
    });
  }, [search, severityFilter, targetTypeFilter, allLogs]);

  // Counts by severity
  const counts = useMemo(() => {
    const c = { info: 0, warning: 0, error: 0, critical: 0 };
    allLogs.forEach((l) => {
      if (l.severity in c) c[l.severity as keyof typeof c]++;
    });
    return c;
  }, [allLogs]);

  const hasFilters =
    search !== "" || severityFilter !== "all" || targetTypeFilter !== "all";

  return (
    <>
      <AppHeader
        breadcrumbs={[
          { label: "Dashboard", href: "/" },
          { label: "Audit Logs" },
        ]}
      />

      <div className="flex flex-1 flex-col gap-6 p-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Audit Logs</h1>
            <p className="text-muted-foreground">
              Full audit trail of every action on the Agentic Bus.
            </p>
          </div>
          <Button variant="outline">
            <Download className="mr-2 h-4 w-4" />
            Export
          </Button>
        </div>

        {/* Summary Cards */}
        <div className="grid gap-4 md:grid-cols-4">
          <Card
            className={`cursor-pointer transition-colors ${
              severityFilter === "all"
                ? "border-primary"
                : "hover:border-muted-foreground/30"
            }`}
            onClick={() => setSeverityFilter("all")}
          >
            <CardContent className="flex items-center justify-between pt-4">
              <div>
                <p className="text-sm text-muted-foreground">Total Events</p>
                <p className="text-2xl font-bold">{allLogs.length}</p>
              </div>
              <Activity className="h-8 w-8 text-muted-foreground/50" />
            </CardContent>
          </Card>

          <Card
            className={`cursor-pointer transition-colors ${
              severityFilter === "warning"
                ? "border-yellow-500"
                : "hover:border-muted-foreground/30"
            }`}
            onClick={() =>
              setSeverityFilter(
                severityFilter === "warning" ? "all" : "warning"
              )
            }
          >
            <CardContent className="flex items-center justify-between pt-4">
              <div>
                <p className="text-sm text-muted-foreground">Warnings</p>
                <p className="text-2xl font-bold text-yellow-500">
                  {counts.warning}
                </p>
              </div>
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-yellow-500/10">
                <span className="text-yellow-500">⚠</span>
              </div>
            </CardContent>
          </Card>

          <Card
            className={`cursor-pointer transition-colors ${
              severityFilter === "error"
                ? "border-red-500"
                : "hover:border-muted-foreground/30"
            }`}
            onClick={() =>
              setSeverityFilter(severityFilter === "error" ? "all" : "error")
            }
          >
            <CardContent className="flex items-center justify-between pt-4">
              <div>
                <p className="text-sm text-muted-foreground">Errors</p>
                <p className="text-2xl font-bold text-red-500">
                  {counts.error}
                </p>
              </div>
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-red-500/10">
                <span className="text-red-500">✕</span>
              </div>
            </CardContent>
          </Card>

          <Card
            className={`cursor-pointer transition-colors ${
              severityFilter === "critical"
                ? "border-red-700"
                : "hover:border-muted-foreground/30"
            }`}
            onClick={() =>
              setSeverityFilter(
                severityFilter === "critical" ? "all" : "critical"
              )
            }
          >
            <CardContent className="flex items-center justify-between pt-4">
              <div>
                <p className="text-sm text-muted-foreground">Critical</p>
                <p className="text-2xl font-bold text-red-700">
                  {counts.critical}
                </p>
              </div>
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-red-700/10">
                <span className="text-red-700">🔴</span>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-3">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search actions, actors, details…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9"
            />
            {search && (
              <Button
                variant="ghost"
                size="icon"
                className="absolute right-1 top-1 h-7 w-7"
                onClick={() => setSearch("")}
              >
                <X className="h-3 w-3" />
              </Button>
            )}
          </div>

          <Select value={targetTypeFilter} onValueChange={setTargetTypeFilter}>
            <SelectTrigger className="w-[160px]">
              <Filter className="mr-2 h-3.5 w-3.5" />
              <SelectValue placeholder="Target type" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All types</SelectItem>
              <SelectItem value="agent">Agent</SelectItem>
              <SelectItem value="session">Session</SelectItem>
              <SelectItem value="llm_config">LLM Config</SelectItem>
              <SelectItem value="system">System</SelectItem>
            </SelectContent>
          </Select>

          {hasFilters && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setSearch("");
                setSeverityFilter("all");
                setTargetTypeFilter("all");
              }}
            >
              <X className="mr-1 h-3 w-3" />
              Clear filters
            </Button>
          )}

          <div className="ml-auto text-sm text-muted-foreground">
            {filtered.length} of {allLogs.length} events
          </div>
        </div>

        {/* Log Table */}
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[180px]">Timestamp</TableHead>
                  <TableHead className="w-[90px]">Severity</TableHead>
                  <TableHead className="w-[180px]">Action</TableHead>
                  <TableHead className="w-[80px]">Type</TableHead>
                  <TableHead>Actor</TableHead>
                  <TableHead>Target</TableHead>
                  <TableHead>Details</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={7}
                      className="py-12 text-center text-muted-foreground"
                    >
                      No audit events match your filters.
                    </TableCell>
                  </TableRow>
                ) : (
                  filtered.map((log) => {
                    const TargetIcon =
                      targetTypeIcons[log.target_type] ?? Server;
                    const group = actionGroup(log.action);
                    return (
                      <TableRow key={log.id}>
                        <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                          {formatTimestamp(log.timestamp)}
                        </TableCell>
                        <TableCell>
                          <SeverityBadge severity={log.severity} />
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="outline"
                            className={`font-mono text-xs ${actionGroupColors[group]}`}
                          >
                            {log.action}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1.5">
                            <TargetIcon className="h-3.5 w-3.5 text-muted-foreground" />
                            <span className="text-xs capitalize text-muted-foreground">
                              {log.target_type}
                            </span>
                          </div>
                        </TableCell>
                        <TableCell className="text-sm">
                          {log.actor}
                        </TableCell>
                        <TableCell className="font-mono text-xs text-muted-foreground">
                          {log.target}
                        </TableCell>
                        <TableCell className="max-w-[350px] truncate text-sm text-muted-foreground">
                          {log.details}
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
