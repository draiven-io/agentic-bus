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

import {
  mockDashboardStats,
  mockPersistentAgents,
  mockSessions,
  mockAuditLog,
} from "@/lib/mock-data";

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

export default function DashboardPage() {
  const stats = mockDashboardStats;
  const recentLogs = mockAuditLog.slice(0, 6);
  const pendingAgents = mockPersistentAgents.filter(
    (a) => a.status === "pending"
  );

  return (
    <>
      <AppHeader breadcrumbs={[{ label: "Dashboard" }]} />

      <div className="flex flex-1 flex-col gap-6 p-6">
        {/* ── Stat Cards ─────────────────────────────────────────── */}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">
                Total Agents
              </CardTitle>
              <Bot className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.total_agents}</div>
              <p className="text-xs text-muted-foreground">
                {stats.approved_agents} approved · {stats.pending_agents}{" "}
                pending
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
              <div className="text-2xl font-bold">{stats.managed_agents}</div>
              <p className="text-xs text-muted-foreground">
                CrewAI-powered agents
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
              <div className="text-2xl font-bold">{stats.active_sessions}</div>
              <p className="text-xs text-muted-foreground">
                {stats.total_sessions_today} total today
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
                {stats.llm_provider}
              </div>
              <p className="text-xs text-muted-foreground">
                Model: {stats.llm_model}
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
                        <Button size="sm" variant="default">
                          <ShieldCheck className="mr-1 h-3 w-3" />
                          Approve
                        </Button>
                        <Button size="sm" variant="destructive">
                          Reject
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* ── Active Sessions ──────────────────────────────────── */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                <Clock className="h-4 w-4" />
                Recent Sessions
              </CardTitle>
              <Badge variant="secondary">{mockSessions.length}</Badge>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {mockSessions.map((session) => (
                  <div
                    key={session.session_id}
                    className="flex items-center justify-between rounded-lg border p-3"
                  >
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm">
                          {session.session_id}
                        </span>
                        <Badge
                          variant={
                            session.phase === "execution"
                              ? "default"
                              : "secondary"
                          }
                        >
                          {session.phase}
                        </Badge>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Requester: {session.requester_id} ·{" "}
                        {session.discovered_agents.length} agents discovered
                      </p>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {timeAgo(session.created_at)}
                    </span>
                  </div>
                ))}
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
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
