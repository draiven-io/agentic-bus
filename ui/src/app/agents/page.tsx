"use client";

import { useState } from "react";
import {
  Bot,
  Shield,
  ShieldCheck,
  ShieldX,
  ShieldBan,
  Trash2,
  Eye,
  Search,
  Plus,
  Wrench,
  Plug,
  X,
} from "lucide-react";

import { AppHeader } from "@/components/app-header";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";

import { mockPersistentAgents, mockManagedAgents } from "@/lib/mock-data";
import type { PersistentAgent, ManagedAgent } from "@/lib/types";

// ── Helpers ──────────────────────────────────────────────────────────

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return "—";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "—";
  return new Date(dateStr).toLocaleString();
}

// ── Agent Detail Dialog ──────────────────────────────────────────────

function PersistentAgentDetail({ agent }: { agent: PersistentAgent }) {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon">
          <Eye className="h-4 w-4" />
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 font-mono">
            <Bot className="h-5 w-5" />
            {agent.agent_id}
          </DialogTitle>
          <DialogDescription>
            {agent.semantic_description}
          </DialogDescription>
        </DialogHeader>
        <ScrollArea className="max-h-[60vh]">
          <div className="space-y-4 pr-4">
            {/* Status row */}
            <div className="flex items-center gap-4">
              <StatusBadge status={agent.status} />
              <Badge variant="outline">v{agent.version}</Badge>
            </div>

            {/* Timestamps */}
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <p className="text-muted-foreground">Enrolled</p>
                <p>{formatDate(agent.enrolled_at)}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Approved</p>
                <p>{formatDate(agent.approved_at)}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Approved By</p>
                <p>{agent.approved_by ?? "—"}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Last Connected</p>
                <p>{formatDate(agent.last_connected_at)}</p>
              </div>
            </div>

            <Separator />

            {/* Capabilities */}
            <div>
              <h4 className="mb-2 text-sm font-semibold">Capabilities</h4>
              {agent.capabilities.length === 0 ? (
                <p className="text-sm text-muted-foreground">None declared</p>
              ) : (
                <div className="space-y-2">
                  {agent.capabilities.map((cap) => (
                    <div
                      key={cap.capability_id}
                      className="rounded-lg border p-3"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-sm font-medium">
                          {cap.capability_id}
                        </span>
                        <div className="flex gap-2 text-xs text-muted-foreground">
                          {cap.estimated_cost != null && (
                            <span>${cap.estimated_cost.toFixed(3)}</span>
                          )}
                          {cap.estimated_latency != null && (
                            <span>{cap.estimated_latency}s</span>
                          )}
                        </div>
                      </div>
                      <p className="mt-1 text-sm text-muted-foreground">
                        {cap.description}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <Separator />

            {/* Scopes & Domains */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <h4 className="mb-2 text-sm font-semibold">Required Scopes</h4>
                <div className="flex flex-wrap gap-1">
                  {agent.required_scopes.map((s) => (
                    <Badge key={s} variant="outline" className="font-mono text-xs">
                      {s}
                    </Badge>
                  ))}
                </div>
              </div>
              <div>
                <h4 className="mb-2 text-sm font-semibold">Domains</h4>
                <div className="flex flex-wrap gap-1">
                  {agent.supported_domains.map((d) => (
                    <Badge key={d} variant="secondary" className="text-xs">
                      {d}
                    </Badge>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}

function ManagedAgentDetail({ agent }: { agent: ManagedAgent }) {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon">
          <Eye className="h-4 w-4" />
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Wrench className="h-5 w-5" />
            {agent.name}
          </DialogTitle>
          <DialogDescription className="font-mono">
            {agent.agent_id}
          </DialogDescription>
        </DialogHeader>
        <ScrollArea className="max-h-[60vh]">
          <div className="space-y-4 pr-4">
            <div className="flex items-center gap-4">
              <StatusBadge status={agent.status} />
              {agent.llm_config_name && (
                <Badge variant="outline">{agent.llm_config_name}</Badge>
              )}
            </div>

            {/* CrewAI Config */}
            <div className="space-y-3 text-sm">
              <div>
                <p className="text-muted-foreground">Role</p>
                <p>{agent.role}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Goal</p>
                <p>{agent.goal}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Backstory</p>
                <p className="text-muted-foreground italic">{agent.backstory}</p>
              </div>
            </div>

            <Separator />

            {/* Agent settings */}
            <div className="grid grid-cols-4 gap-4 text-sm">
              <div>
                <p className="text-muted-foreground">Max Iterations</p>
                <p>{agent.max_iter}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Max RPM</p>
                <p>{agent.max_rpm ?? "—"}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Verbose</p>
                <p>{agent.verbose ? "Yes" : "No"}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Memory</p>
                <p>{agent.memory ? "Yes" : "No"}</p>
              </div>
            </div>

            <Separator />

            {/* Tools */}
            <div>
              <h4 className="mb-2 text-sm font-semibold">Tools</h4>
              <div className="flex flex-wrap gap-1">
                {agent.tools.length === 0 ? (
                  <p className="text-sm text-muted-foreground">None</p>
                ) : (
                  agent.tools.map((t) => (
                    <Badge key={t} variant="outline" className="font-mono text-xs">
                      {t}
                    </Badge>
                  ))
                )}
              </div>
            </div>

            {/* Capabilities */}
            {agent.capabilities.length > 0 && (
              <>
                <Separator />
                <div>
                  <h4 className="mb-2 text-sm font-semibold">Capabilities</h4>
                  <div className="space-y-2">
                    {agent.capabilities.map((cap) => (
                      <div
                        key={cap.id}
                        className="rounded-lg border p-3"
                      >
                        <span className="font-mono text-sm font-medium">
                          {cap.capability_id}
                        </span>
                        <p className="mt-1 text-sm text-muted-foreground">
                          {cap.description}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}

// ── Main Page ────────────────────────────────────────────────────────

export default function AgentsPage() {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");

  // Filter persistent agents
  const filteredPersistent = mockPersistentAgents.filter((a) => {
    const matchesSearch =
      a.agent_id.toLowerCase().includes(search.toLowerCase()) ||
      a.semantic_description.toLowerCase().includes(search.toLowerCase());
    const matchesStatus =
      statusFilter === "all" || a.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  // Filter managed agents
  const filteredManaged = mockManagedAgents.filter((a) => {
    const matchesSearch =
      a.agent_id.toLowerCase().includes(search.toLowerCase()) ||
      a.name.toLowerCase().includes(search.toLowerCase()) ||
      a.role.toLowerCase().includes(search.toLowerCase());
    return matchesSearch;
  });

  return (
    <>
      <AppHeader
        breadcrumbs={[
          { label: "Dashboard", href: "/" },
          { label: "Agents" },
        ]}
      />

      <div className="flex flex-1 flex-col gap-6 p-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Agents</h1>
            <p className="text-muted-foreground">
              Manage persistent and CrewAI-managed agents on the bus.
            </p>
          </div>
          <Button>
            <Plus className="mr-2 h-4 w-4" />
            Create Agent
          </Button>
        </div>

        {/* Tabs */}
        <Tabs defaultValue="persistent" className="space-y-4">
          <div className="flex items-center justify-between gap-4">
            <TabsList>
              <TabsTrigger value="persistent" className="gap-2">
                <Plug className="h-4 w-4" />
                Persistent
                <Badge variant="secondary" className="ml-1">
                  {mockPersistentAgents.length}
                </Badge>
              </TabsTrigger>
              <TabsTrigger value="managed" className="gap-2">
                <Wrench className="h-4 w-4" />
                Managed
                <Badge variant="secondary" className="ml-1">
                  {mockManagedAgents.length}
                </Badge>
              </TabsTrigger>
            </TabsList>

            <div className="relative w-72">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search agents…"
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
          </div>

          {/* ── Persistent Agents Tab ────────────────────────── */}
          <TabsContent value="persistent" className="space-y-4">
            {/* Status filter chips */}
            <div className="flex gap-2">
              {["all", "approved", "pending", "rejected", "revoked"].map(
                (s) => (
                  <Button
                    key={s}
                    variant={statusFilter === s ? "default" : "outline"}
                    size="sm"
                    onClick={() => setStatusFilter(s)}
                    className="capitalize"
                  >
                    {s === "all" ? "All" : s}
                  </Button>
                )
              )}
            </div>

            <Card>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Agent ID</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Version</TableHead>
                      <TableHead>Capabilities</TableHead>
                      <TableHead>Domains</TableHead>
                      <TableHead>Last Connected</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredPersistent.length === 0 ? (
                      <TableRow>
                        <TableCell
                          colSpan={7}
                          className="py-8 text-center text-muted-foreground"
                        >
                          No agents match your filters.
                        </TableCell>
                      </TableRow>
                    ) : (
                      filteredPersistent.map((agent) => (
                        <TableRow key={agent.agent_id}>
                          <TableCell>
                            <div className="space-y-1">
                              <span className="font-mono text-sm font-medium">
                                {agent.agent_id}
                              </span>
                              <p className="max-w-[250px] truncate text-xs text-muted-foreground">
                                {agent.semantic_description}
                              </p>
                            </div>
                          </TableCell>
                          <TableCell>
                            <StatusBadge status={agent.status} />
                          </TableCell>
                          <TableCell>
                            <Badge variant="outline">v{agent.version}</Badge>
                          </TableCell>
                          <TableCell>
                            <span className="text-sm">
                              {agent.capabilities.length}
                            </span>
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-wrap gap-1">
                              {agent.supported_domains.map((d) => (
                                <Badge
                                  key={d}
                                  variant="secondary"
                                  className="text-xs"
                                >
                                  {d}
                                </Badge>
                              ))}
                            </div>
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {timeAgo(agent.last_connected_at)}
                          </TableCell>
                          <TableCell className="text-right">
                            <div className="flex items-center justify-end gap-1">
                              <PersistentAgentDetail agent={agent} />
                              {agent.status === "pending" && (
                                <>
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="text-green-500 hover:text-green-600"
                                    title="Approve"
                                  >
                                    <ShieldCheck className="h-4 w-4" />
                                  </Button>
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="text-red-500 hover:text-red-600"
                                    title="Reject"
                                  >
                                    <ShieldX className="h-4 w-4" />
                                  </Button>
                                </>
                              )}
                              {agent.status === "approved" && (
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="text-yellow-500 hover:text-yellow-600"
                                  title="Revoke"
                                >
                                  <ShieldBan className="h-4 w-4" />
                                </Button>
                              )}
                              <Button
                                variant="ghost"
                                size="icon"
                                className="text-destructive hover:text-destructive"
                                title="Delete"
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </TabsContent>

          {/* ── Managed Agents Tab ───────────────────────────── */}
          <TabsContent value="managed" className="space-y-4">
            <Card>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Agent ID</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Role</TableHead>
                      <TableHead>Tools</TableHead>
                      <TableHead>Capabilities</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredManaged.length === 0 ? (
                      <TableRow>
                        <TableCell
                          colSpan={7}
                          className="py-8 text-center text-muted-foreground"
                        >
                          No managed agents found.
                        </TableCell>
                      </TableRow>
                    ) : (
                      filteredManaged.map((agent) => (
                        <TableRow key={agent.agent_id}>
                          <TableCell className="font-medium">
                            {agent.name}
                          </TableCell>
                          <TableCell className="font-mono text-sm text-muted-foreground">
                            {agent.agent_id}
                          </TableCell>
                          <TableCell>
                            <StatusBadge status={agent.status} />
                          </TableCell>
                          <TableCell className="max-w-[200px] truncate text-sm">
                            {agent.role}
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-wrap gap-1">
                              {agent.tools.map((t) => (
                                <Badge
                                  key={t}
                                  variant="outline"
                                  className="font-mono text-xs"
                                >
                                  {t}
                                </Badge>
                              ))}
                            </div>
                          </TableCell>
                          <TableCell className="text-sm">
                            {agent.capabilities.length}
                          </TableCell>
                          <TableCell className="text-right">
                            <div className="flex items-center justify-end gap-1">
                              <ManagedAgentDetail agent={agent} />
                              {agent.status === "draft" && (
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="text-green-500 hover:text-green-600"
                                  title="Activate"
                                >
                                  <ShieldCheck className="h-4 w-4" />
                                </Button>
                              )}
                              {agent.status === "active" && (
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="text-yellow-500 hover:text-yellow-600"
                                  title="Disable"
                                >
                                  <ShieldBan className="h-4 w-4" />
                                </Button>
                              )}
                              <Button
                                variant="ghost"
                                size="icon"
                                className="text-destructive hover:text-destructive"
                                title="Delete"
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </>
  );
}
