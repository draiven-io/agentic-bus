"use client";

import {
  Bot,
  Clock,
  Activity,
  ShieldCheck,
  AlertTriangle,
  Cpu,
  ArrowUpRight,
  Users,
  Zap,
  Loader2,
  CheckCircle2,
  XCircle,
  Ban,
  ShieldX,
  Network,
} from "lucide-react";
import Link from "next/link";

import { AppHeader } from "@/components/app-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SeverityBadge } from "@/components/status-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";

import { useAsync } from "@/hooks/use-async";
import {
  approveAgent,
  fetchAuditLog,
  fetchDashboardStats,
  fetchPersistentAgents,
  fetchSessionArchives,
  rejectAgent,
} from "@/lib/api";

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

const negotiationOutcome: Record<
  string,
  {
    icon: typeof CheckCircle2;
    label: string;
    badgeVariant: "default" | "secondary" | "destructive" | "outline";
  }
> = {
  success: { icon: CheckCircle2, label: "Success", badgeVariant: "default" },
  error: { icon: XCircle, label: "Error", badgeVariant: "destructive" },
  partial_failure: { icon: AlertTriangle, label: "Partial", badgeVariant: "outline" },
  denied: { icon: ShieldX, label: "Denied", badgeVariant: "destructive" },
  rejected: { icon: Ban, label: "Rejected", badgeVariant: "outline" },
  cancelled: { icon: Ban, label: "Cancelled", badgeVariant: "secondary" },
};

export default function DashboardPage() {
  const {
    data: stats,
    loading: statsLoading,
    refetch: refetchStats,
  } = useAsync(() => fetchDashboardStats());
  const {
    data: persistentAgents,
    loading: agentsLoading,
    refetch: refetchAgents,
  } = useAsync(() => fetchPersistentAgents());
  const { data: negotiations, loading: negotiationsLoading } = useAsync(() =>
    fetchSessionArchives({ limit: 5 }),
  );
  const { data: auditLog, loading: auditLoading } = useAsync(() =>
    fetchAuditLog(),
  );

  const recentLogs = (auditLog ?? []).slice(0, 6);
  const pendingAgents = (persistentAgents ?? []).filter(
    (a) => a.status === "pending",
  );

  const handleApprove = async (agentId: string) => {
    await approveAgent(agentId);
    refetchAgents();
    refetchStats();
  };

  const handleReject = async (agentId: string) => {
    await rejectAgent(agentId);
    refetchAgents();
    refetchStats();
  };

  const isLoading = statsLoading || agentsLoading || negotiationsLoading || auditLoading;

  return (
    <>
      <AppHeader breadcrumbs={[{ label: "Dashboard" }]} />

      <div className="flex flex-1 flex-col gap-6 p-6">
        {isLoading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading dashboard data…
          </div>
        )}

        {/* ── Stat Cards ─────────────────────────────────────────── */}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">
                Total Agents
              </CardTitle>
              <Bot className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {stats?.total_agents ?? "—"}
              </div>
              <p className="text-xs text-muted-foreground">
                {stats?.approved_agents ?? 0} approved ·{" "}
                {stats?.pending_agents ?? 0} pending
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">
                Managed Agents
              </CardTitle>
              <Users className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {stats?.managed_agents ?? "—"}
              </div>
              <p className="text-xs text-muted-foreground">
                AgBus-powered agents
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">
                Ephemeral Agents
              </CardTitle>
              <Zap className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {stats?.ephemeral_agents ?? "—"}
              </div>
              <p className="text-xs text-muted-foreground">
                Currently connected
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">
                Active Sessions
              </CardTitle>
              <Activity className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {stats?.active_sessions ?? "—"}
              </div>
              <p className="text-xs text-muted-foreground">
                {stats?.total_sessions_today ?? 0} total today
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">
                LLM Provider
              </CardTitle>
              <Cpu className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold capitalize">
                {stats?.llm_provider ?? "—"}
              </div>
              <p className="text-xs text-muted-foreground">
                Model: {stats?.llm_model ?? "—"}
              </p>
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          {/* ── Pending Approvals ────────────────────────────────── */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-yellow-500" />
                Pending Approvals
              </CardTitle>
              <Badge variant="secondary">{pendingAgents.length}</Badge>
            </CardHeader>
            <CardContent>
              {pendingAgents.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No pending enrolments 🎉
                </p>
              ) : (
                <div className="space-y-3">
                  {pendingAgents.map((agent) => (
                    <div
                      key={agent.agent_id}
                      className="flex items-center justify-between rounded-lg border p-3"
                    >
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-sm font-medium">
                            {agent.agent_id}
                          </span>
                          <Badge variant="outline">v{agent.version}</Badge>
                        </div>
                        <p className="text-xs text-muted-foreground line-clamp-1">
                          {agent.semantic_description}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          Enrolled {timeAgo(agent.enrolled_at)}
                        </p>
                      </div>
                      <div className="flex gap-2">
                        <Button
                          size="sm"
                          variant="default"
                          onClick={() => handleApprove(agent.agent_id)}
                        >
                          <ShieldCheck className="mr-1 h-3 w-3" />
                          Approve
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => handleReject(agent.agent_id)}
                        >
                          Reject
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* ── Recent Negotiations ─────────────────────────────── */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                <Network className="h-4 w-4 text-primary" />
                Recent Negotiations
              </CardTitle>
              <Button variant="ghost" size="sm" asChild>
                <Link href="/history">
                  View all
                  <ArrowUpRight className="ml-1 h-3 w-3" />
                </Link>
              </Button>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {(negotiations ?? []).map((neg) => {
                  const outcomeConf = negotiationOutcome[neg.outcome] ?? negotiationOutcome.error;
                  const OutcomeIcon = outcomeConf.icon;
                  return (
                    <div
                      key={neg.session_id}
                      className="flex items-center justify-between rounded-lg border p-3"
                    >
                      <div className="space-y-1 min-w-0 flex-1 mr-3">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium truncate">
                            {neg.intent_text || neg.session_id}
                          </span>
                          <Badge variant={outcomeConf.badgeVariant} className="gap-1 shrink-0">
                            <OutcomeIcon className="size-3" />
                            {outcomeConf.label}
                          </Badge>
                        </div>
                        <p className="text-xs text-muted-foreground">
                          {neg.agent_count} agent{neg.agent_count !== 1 ? "s" : ""} · {neg.step_count} step{neg.step_count !== 1 ? "s" : ""}
                          {neg.intent_domain ? ` · ${neg.intent_domain}` : ""}
                        </p>
                      </div>
                      <span className="text-xs text-muted-foreground whitespace-nowrap">
                        {timeAgo(neg.created_at)}
                      </span>
                    </div>
                  );
                })}
                {(negotiations ?? []).length === 0 && !negotiationsLoading && (
                  <p className="text-sm text-muted-foreground">
                    No negotiations yet
                  </p>
                )}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* ── Recent Audit Log ───────────────────────────────────── */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Recent Activity</CardTitle>
            <Button variant="ghost" size="sm" asChild>
              <Link href="/audit">
                View all
                <ArrowUpRight className="ml-1 h-3 w-3" />
              </Link>
            </Button>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[140px]">Time</TableHead>
                  <TableHead className="w-[100px]">Severity</TableHead>
                  <TableHead className="w-[180px]">Action</TableHead>
                  <TableHead>Actor</TableHead>
                  <TableHead>Details</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recentLogs.map((log) => (
                  <TableRow key={log.id}>
                    <TableCell className="text-xs text-muted-foreground">
                      {timeAgo(log.timestamp)}
                    </TableCell>
                    <TableCell>
                      <SeverityBadge severity={log.severity} />
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {log.action}
                    </TableCell>
                    <TableCell className="text-sm">{log.actor}</TableCell>
                    <TableCell className="max-w-[300px] truncate text-sm text-muted-foreground">
                      {log.details}
                    </TableCell>
                  </TableRow>
                ))}
                {recentLogs.length === 0 && !auditLoading && (
                  <TableRow>
                    <TableCell
                      colSpan={5}
                      className="py-8 text-center text-muted-foreground"
                    >
                      No activity yet
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
