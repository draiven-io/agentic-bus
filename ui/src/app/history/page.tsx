"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import {
  Search,
  Filter,
  Clock,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ShieldX,
  Ban,
  ChevronRight,
  Bot,
  ArrowUpDown,
  Trash2,
  Network,
  Activity,
  Terminal,
  X,
  Star,
  Timer,
  FileText,
} from "lucide-react";

import { AppHeader } from "@/components/app-header";
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
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

import { useAsync } from "@/hooks/use-async";
import {
  fetchSessionArchives,
  fetchSessionArchive,
  deleteSessionArchive,
} from "@/lib/api";
import type {
  SessionArchiveListItem,
  SessionArchiveDetail,
} from "@/lib/types";

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

function formatDuration(seconds: number): string {
  if (seconds < 1) return "<1s";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}m ${secs}s`;
}

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max) + "…";
}

// ── Outcome visuals ─────────────────────────────────────────────────

const outcomeConfig: Record<
  string,
  { icon: typeof CheckCircle2; label: string; className: string; badgeVariant: "default" | "secondary" | "destructive" | "outline" }
> = {
  success: {
    icon: CheckCircle2,
    label: "Success",
    className: "text-emerald-400",
    badgeVariant: "default",
  },
  error: {
    icon: XCircle,
    label: "Error",
    className: "text-red-400",
    badgeVariant: "destructive",
  },
  partial_failure: {
    icon: AlertTriangle,
    label: "Partial",
    className: "text-orange-400",
    badgeVariant: "outline",
  },
  denied: {
    icon: ShieldX,
    label: "Denied",
    className: "text-red-400",
    badgeVariant: "destructive",
  },
  rejected: {
    icon: Ban,
    label: "Rejected",
    className: "text-zinc-400",
    badgeVariant: "outline",
  },
  cancelled: {
    icon: Ban,
    label: "Cancelled",
    className: "text-zinc-500",
    badgeVariant: "secondary",
  },
};

function OutcomeBadge({ outcome }: { outcome: string }) {
  const config = outcomeConfig[outcome] ?? outcomeConfig.error;
  const Icon = config.icon;
  return (
    <Badge variant={config.badgeVariant} className="gap-1">
      <Icon className="size-3" />
      {config.label}
    </Badge>
  );
}

// ── Detail panel ────────────────────────────────────────────────────

function ArchiveDetailPanel({
  sessionId,
  onClose,
}: {
  sessionId: string;
  onClose: () => void;
}) {
  const { data: archive, loading, error } = useAsync(
    () => fetchSessionArchive(sessionId),
    [sessionId],
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-pulse text-zinc-500 text-sm">Loading archive…</div>
      </div>
    );
  }

  if (error || !archive) {
    return (
      <div className="flex items-center justify-center h-64 text-red-400 text-sm">
        {error ?? "Archive not found"}
      </div>
    );
  }

  const config = outcomeConfig[archive.outcome] ?? outcomeConfig.error;
  const OutcomeIcon = config.icon;
  const plan = archive.composition_plan;
  const steps = (plan?.steps as { agent_id: string; capability_id: string; description: string }[]) ?? [];

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <OutcomeIcon className={`size-5 ${config.className}`} />
          <span className="text-lg font-semibold text-zinc-100">
            {archive.intent_text ? truncate(archive.intent_text, 80) : "Untitled Session"}
          </span>
        </div>
        <div className="flex flex-wrap gap-2 text-xs text-zinc-500">
          <span className="font-mono">{archive.session_id.slice(0, 8)}…</span>
          <Separator orientation="vertical" className="h-3" />
          <span>{formatTimestamp(archive.created_at)}</span>
          <Separator orientation="vertical" className="h-3" />
          <span>{formatDuration(archive.duration_seconds)}</span>
          <Separator orientation="vertical" className="h-3" />
          <span>by {archive.requester_id}</span>
        </div>
      </div>

      <Separator />

      {/* Tabs */}
      <Tabs defaultValue="timeline" className="flex-1">
        <TabsList className="bg-zinc-900">
          <TabsTrigger value="timeline" className="text-xs gap-1.5">
            <Activity className="size-3" /> Timeline
            <Badge variant="secondary" className="ml-1 text-[9px] px-1.5 py-0 h-4">
              {archive.timeline_events.length}
            </Badge>
          </TabsTrigger>
          <TabsTrigger value="plan" className="text-xs gap-1.5">
            <Network className="size-3" /> Plan
            <Badge variant="secondary" className="ml-1 text-[9px] px-1.5 py-0 h-4">
              {steps.length}
            </Badge>
          </TabsTrigger>
          <TabsTrigger value="results" className="text-xs gap-1.5">
            <Terminal className="size-3" /> Results
          </TabsTrigger>
          {(archive.output || (archive.agent_metrics && archive.agent_metrics.length > 0)) && (
            <TabsTrigger value="output" className="text-xs gap-1.5">
              <FileText className="size-3" /> Output
            </TabsTrigger>
          )}
        </TabsList>

        {/* Timeline tab */}
        <TabsContent value="timeline" className="mt-3 max-h-[60vh] overflow-y-auto">
          {archive.timeline_events.length === 0 ? (
            <p className="text-sm text-zinc-500">No timeline events recorded.</p>
          ) : (
            <div className="space-y-1">
              {archive.timeline_events.map((evt, i) => (
                <div
                  key={evt.id || i}
                  className="flex items-start gap-3 rounded-md px-3 py-2 text-xs hover:bg-zinc-800/50"
                >
                  <span className="shrink-0 font-mono text-zinc-600 mt-0.5">
                    {new Date(evt.timestamp).toLocaleTimeString("en-GB", {
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    })}
                  </span>
                  <Badge
                    variant="outline"
                    className="shrink-0 text-[9px] px-1.5 py-0"
                  >
                    {evt.category}
                  </Badge>
                  <span className="text-zinc-300 break-all">{evt.summary}</span>
                </div>
              ))}
            </div>
          )}
        </TabsContent>

        {/* Plan tab */}
        <TabsContent value="plan" className="mt-3 max-h-[60vh] overflow-y-auto">
          {steps.length === 0 ? (
            <p className="text-sm text-zinc-500">No composition plan recorded.</p>
          ) : (
            <div className="space-y-2">
              {steps.map((step, i) => (
                <div
                  key={i}
                  className="flex items-start gap-3 rounded-lg border border-zinc-800 p-3"
                >
                  <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-zinc-800 text-xs font-bold text-zinc-400">
                    {i + 1}
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <Bot className="size-3.5 text-violet-400" />
                      <span className="text-sm font-medium text-zinc-200">
                        {step.agent_id}
                      </span>
                      <Badge variant="outline" className="text-[9px] px-1.5 py-0">
                        {step.capability_id}
                      </Badge>
                    </div>
                    <p className="mt-1 text-xs text-zinc-500">{step.description}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </TabsContent>

        {/* Results tab */}
        <TabsContent value="results" className="mt-3 max-h-[60vh] overflow-y-auto">
          {archive.execution_results.length === 0 ? (
            <p className="text-sm text-zinc-500">No execution results recorded.</p>
          ) : (
            <div className="space-y-3">
              {archive.execution_results.map((result, i) => (
                <Card key={i} className="bg-zinc-900 border-zinc-800">
                  <CardContent className="p-3">
                    <pre className="text-xs text-zinc-400 whitespace-pre-wrap break-all font-mono">
                      {JSON.stringify(result, null, 2)}
                    </pre>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        {/* Output & Agent Metrics tab */}
        <TabsContent value="output" className="mt-3 max-h-[60vh] overflow-y-auto">
          <div className="space-y-4">
            {/* Synthesised output */}
            {archive.output && (
              <div>
                <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold text-zinc-200">
                  <FileText className="size-4" />
                  Synthesised Output
                </h4>
                <Card className="bg-zinc-900 border-zinc-800">
                  <CardContent className="p-4">
                    <p className="text-sm text-zinc-300 whitespace-pre-wrap">
                      {archive.output}
                    </p>
                  </CardContent>
                </Card>
                {archive.output_summary && (
                  <p className="mt-2 text-xs text-zinc-500 italic">
                    {archive.output_summary}
                  </p>
                )}
              </div>
            )}

            {/* Per-agent metrics */}
            {archive.agent_metrics && archive.agent_metrics.length > 0 && (
              <div>
                <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold text-zinc-200">
                  <Bot className="size-4" />
                  Agent Performance
                </h4>
                <div className="space-y-2">
                  {archive.agent_metrics.map((m, i) => {
                    const scoreVal = m.quality_score ?? 0;
                    const scoreClass =
                      scoreVal >= 8
                        ? "text-emerald-400"
                        : scoreVal >= 6
                          ? "text-yellow-400"
                          : scoreVal >= 4
                            ? "text-orange-400"
                            : "text-red-400";
                    return (
                      <Card key={i} className="bg-zinc-900 border-zinc-800">
                        <CardContent className="p-3">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <Bot className="size-3.5 text-violet-400" />
                              <span className="text-sm font-medium text-zinc-200 font-mono">
                                {m.agent_id}
                              </span>
                            </div>
                            <div className="flex items-center gap-4 text-xs">
                              <span className={`flex items-center gap-1 font-medium ${scoreClass}`}>
                                <Star className="size-3" />
                                {scoreVal.toFixed(1)}/10
                              </span>
                              <span className="flex items-center gap-1 text-zinc-400">
                                <Timer className="size-3" />
                                {m.latency_ms != null
                                  ? m.latency_ms < 1000
                                    ? `${Math.round(m.latency_ms)}ms`
                                    : `${(m.latency_ms / 1000).toFixed(1)}s`
                                  : "—"}
                              </span>
                              {m.retries > 0 && (
                                <Badge variant="outline" className="text-[9px] px-1.5 py-0 border-orange-500/30 text-orange-400">
                                  {m.retries} retry{m.retries > 1 ? "ies" : ""}
                                </Badge>
                              )}
                            </div>
                          </div>
                          {m.quality_rationale && (
                            <p className="mt-2 text-xs text-zinc-500 italic">
                              {m.quality_rationale}
                            </p>
                          )}
                        </CardContent>
                      </Card>
                    );
                  })}
                </div>
              </div>
            )}

            {!archive.output &&
              (!archive.agent_metrics || archive.agent_metrics.length === 0) && (
                <p className="text-sm text-zinc-500">No output or metrics available.</p>
              )}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ── Main page ───────────────────────────────────────────────────────

export default function HistoryPage() {
  const {
    data: archives,
    loading,
    error,
    refetch,
  } = useAsync(() => fetchSessionArchives({ limit: 200 }), []);
  const [search, setSearch] = useState("");
  const [outcomeFilter, setOutcomeFilter] = useState<string>("all");
  const [selectedSession, setSelectedSession] = useState<string | null>(null);

  const filtered = useMemo(() => {
    if (!archives) return [];
    return archives.filter((a) => {
      if (outcomeFilter !== "all" && a.outcome !== outcomeFilter) return false;
      if (search) {
        const q = search.toLowerCase();
        return (
          a.intent_text.toLowerCase().includes(q) ||
          a.session_id.toLowerCase().includes(q) ||
          a.requester_id.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [archives, search, outcomeFilter]);

  // Stats
  const stats = useMemo(() => {
    if (!archives) return { total: 0, success: 0, error: 0, avgDuration: 0 };
    const success = archives.filter((a) => a.outcome === "success").length;
    const errCount = archives.filter((a) =>
      ["error", "partial_failure", "denied"].includes(a.outcome),
    ).length;
    const avgDuration =
      archives.length > 0
        ? archives.reduce((sum, a) => sum + a.duration_seconds, 0) /
          archives.length
        : 0;
    return { total: archives.length, success, error: errCount, avgDuration };
  }, [archives]);

  const handleDelete = async (sessionId: string) => {
    try {
      await deleteSessionArchive(sessionId);
      refetch();
      if (selectedSession === sessionId) setSelectedSession(null);
    } catch {
      // TODO: toast
    }
  };

  return (
    <>
      <AppHeader breadcrumbs={[{ label: "History" }]} />

      <div className="flex flex-1 flex-col gap-4 p-4 overflow-auto">
        {/* Stat cards */}
        <div className="grid grid-cols-4 gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Total Executions
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.total}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-emerald-400/80">
                Successful
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-emerald-400">
                {stats.success}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-red-400/80">
                Failed / Denied
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-red-400">
                {stats.error}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Avg Duration
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {formatDuration(stats.avgDuration)}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search by intent, session ID, or requester…"
              className="pl-9"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <Select value={outcomeFilter} onValueChange={setOutcomeFilter}>
            <SelectTrigger className="w-[160px]">
              <Filter className="mr-2 size-4" />
              <SelectValue placeholder="Outcome" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All outcomes</SelectItem>
              <SelectItem value="success">Success</SelectItem>
              <SelectItem value="error">Error</SelectItem>
              <SelectItem value="partial_failure">Partial</SelectItem>
              <SelectItem value="denied">Denied</SelectItem>
              <SelectItem value="rejected">Rejected</SelectItem>
              <SelectItem value="cancelled">Cancelled</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Table */}
        <Card>
          <CardContent className="p-0">
            {loading ? (
              <div className="flex items-center justify-center py-16 text-muted-foreground text-sm">
                Loading history…
              </div>
            ) : error ? (
              <div className="flex items-center justify-center py-16 text-red-400 text-sm">
                {error}
              </div>
            ) : filtered.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 gap-2">
                <Clock className="size-8 text-zinc-600" />
                <p className="text-sm text-zinc-500">
                  {archives?.length === 0
                    ? "No executions yet. Run a negotiation to see history here."
                    : "No results match your filters."}
                </p>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[45%]">Intent</TableHead>
                    <TableHead>Outcome</TableHead>
                    <TableHead>Agents</TableHead>
                    <TableHead>Duration</TableHead>
                    <TableHead>
                      <span className="flex items-center gap-1">
                        <ArrowUpDown className="size-3" /> Time
                      </span>
                    </TableHead>
                    <TableHead className="w-10" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((archive) => (
                    <TableRow
                      key={archive.session_id}
                      className="cursor-pointer hover:bg-zinc-800/50"
                      onClick={() => setSelectedSession(archive.session_id)}
                    >
                      <TableCell>
                        <div className="flex flex-col gap-0.5">
                          <span className="text-sm font-medium text-zinc-200">
                            {archive.intent_text
                              ? truncate(archive.intent_text, 70)
                              : "Untitled"}
                          </span>
                          <span className="text-xs text-zinc-600 font-mono">
                            {archive.session_id.slice(0, 8)}…
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <OutcomeBadge outcome={archive.outcome} />
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1 text-sm text-zinc-400">
                          <Bot className="size-3.5" />
                          {archive.agent_count}
                          <span className="text-zinc-600 text-xs">
                            ({archive.step_count} step{archive.step_count !== 1 ? "s" : ""})
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <span className="text-sm text-zinc-400">
                          {formatDuration(archive.duration_seconds)}
                        </span>
                      </TableCell>
                      <TableCell>
                        <span className="text-xs text-zinc-500">
                          {formatTimestamp(archive.dissolved_at)}
                        </span>
                      </TableCell>
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-7 text-zinc-600 hover:text-red-400"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDelete(archive.session_id);
                          }}
                        >
                          <Trash2 className="size-3.5" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Detail drawer */}
      <Sheet
        open={!!selectedSession}
        onOpenChange={(open) => {
          if (!open) setSelectedSession(null);
        }}
      >
        <SheetContent className="sm:max-w-xl w-full overflow-y-auto">
          <SheetHeader>
            <SheetTitle>Session Archive</SheetTitle>
          </SheetHeader>
          {selectedSession && (
            <ArchiveDetailPanel
              sessionId={selectedSession}
              onClose={() => setSelectedSession(null)}
            />
          )}
        </SheetContent>
      </Sheet>
    </>
  );
}
