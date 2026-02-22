"use client";

import { useState } from "react";
import {
  Shield,
  Plus,
  Trash2,
  Pencil,
  Search,
  X,
  ShieldCheck,
  ShieldX,
  ShieldAlert,
  ToggleLeft,
  ToggleRight,
} from "lucide-react";

import { AppHeader } from "@/components/app-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
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
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { useAsync } from "@/hooks/use-async";
import {
  fetchIBACRules,
  createIBACRule,
  updateIBACRule,
  deleteIBACRule,
} from "@/lib/api";
import type {
  IBACRule,
  IBACRuleAction,
  IBACEvaluationPoint,
  IBACRuleConditions,
} from "@/lib/types";

// ── Constants ────────────────────────────────────────────────────────

const EVALUATION_POINTS: { value: IBACEvaluationPoint; label: string }[] = [
  { value: "intent_admission", label: "Intent Admission" },
  { value: "offer_eligibility", label: "Offer Eligibility" },
  { value: "negotiation_acceptance", label: "Negotiation Acceptance" },
  { value: "execution_authorization", label: "Execution Authorization" },
  { value: "artifact_emission", label: "Artifact Emission" },
];

// ── Helpers ──────────────────────────────────────────────────────────

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "—";
  return new Date(dateStr).toLocaleString();
}

function epLabel(ep: string): string {
  return EVALUATION_POINTS.find((e) => e.value === ep)?.label ?? ep;
}

// ── Conditions Editor ────────────────────────────────────────────────

function ConditionsEditor({
  conditions,
  onChange,
}: {
  conditions: IBACRuleConditions;
  onChange: (c: IBACRuleConditions) => void;
}) {
  function csvToList(csv: string): string[] {
    return csv
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  }
  function listToCsv(list: string[] | undefined): string {
    return (list ?? []).join(", ");
  }

  return (
    <div className="grid gap-3">
      <div className="grid gap-1.5">
        <Label htmlFor="cond-keywords">
          Intent Keywords{" "}
          <span className="text-xs text-muted-foreground">(comma-separated)</span>
        </Label>
        <Input
          id="cond-keywords"
          placeholder="delete, drop, password, credentials"
          value={listToCsv(conditions.intent_keywords)}
          onChange={(e) =>
            onChange({ ...conditions, intent_keywords: csvToList(e.target.value) })
          }
        />
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="cond-patterns">
          Intent Regex Patterns{" "}
          <span className="text-xs text-muted-foreground">(comma-separated)</span>
        </Label>
        <Input
          id="cond-patterns"
          placeholder="\\bDROP\\s+TABLE\\b, \\bpassword\\b"
          value={listToCsv(conditions.intent_patterns)}
          onChange={(e) =>
            onChange({ ...conditions, intent_patterns: csvToList(e.target.value) })
          }
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="grid gap-1.5">
          <Label htmlFor="cond-blocked-agents">Blocked Agents</Label>
          <Input
            id="cond-blocked-agents"
            placeholder="agent-a, agent-b"
            value={listToCsv(conditions.blocked_agents)}
            onChange={(e) =>
              onChange({ ...conditions, blocked_agents: csvToList(e.target.value) })
            }
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="cond-allowed-agents">Allowed Agents</Label>
          <Input
            id="cond-allowed-agents"
            placeholder="trusted-agent-1"
            value={listToCsv(conditions.allowed_agents)}
            onChange={(e) =>
              onChange({ ...conditions, allowed_agents: csvToList(e.target.value) })
            }
          />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="grid gap-1.5">
          <Label htmlFor="cond-blocked-scopes">Blocked Scopes</Label>
          <Input
            id="cond-blocked-scopes"
            placeholder="admin:write, finance:delete"
            value={listToCsv(conditions.blocked_scopes)}
            onChange={(e) =>
              onChange({ ...conditions, blocked_scopes: csvToList(e.target.value) })
            }
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="cond-allowed-scopes">Allowed Scopes</Label>
          <Input
            id="cond-allowed-scopes"
            placeholder="data:read, logistics:*"
            value={listToCsv(conditions.allowed_scopes)}
            onChange={(e) =>
              onChange({ ...conditions, allowed_scopes: csvToList(e.target.value) })
            }
          />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="grid gap-1.5">
          <Label htmlFor="cond-blocked-domains">Blocked Domains</Label>
          <Input
            id="cond-blocked-domains"
            placeholder="pii, financial"
            value={listToCsv(conditions.blocked_domains)}
            onChange={(e) =>
              onChange({ ...conditions, blocked_domains: csvToList(e.target.value) })
            }
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="cond-allowed-domains">Allowed Domains</Label>
          <Input
            id="cond-allowed-domains"
            placeholder="logistics, inventory"
            value={listToCsv(conditions.allowed_domains)}
            onChange={(e) =>
              onChange({ ...conditions, allowed_domains: csvToList(e.target.value) })
            }
          />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="grid gap-1.5">
          <Label htmlFor="cond-max-agents">Max Agents in Composition</Label>
          <Input
            id="cond-max-agents"
            type="number"
            placeholder="No limit"
            value={conditions.max_agents ?? ""}
            onChange={(e) =>
              onChange({
                ...conditions,
                max_agents: e.target.value ? parseInt(e.target.value, 10) : undefined,
              })
            }
          />
        </div>
        <div className="flex items-end gap-2 pb-0.5">
          <input
            type="checkbox"
            id="cond-human"
            checked={conditions.require_human_approval ?? false}
            onChange={(e) =>
              onChange({
                ...conditions,
                require_human_approval: e.target.checked || undefined,
              })
            }
            className="h-4 w-4"
          />
          <Label htmlFor="cond-human">Require Human Approval</Label>
        </div>
      </div>
    </div>
  );
}

// ── Evaluation Point Picker ──────────────────────────────────────────

function EvalPointPicker({
  selected,
  onChange,
}: {
  selected: IBACEvaluationPoint[];
  onChange: (pts: IBACEvaluationPoint[]) => void;
}) {
  function toggle(pt: IBACEvaluationPoint) {
    if (selected.includes(pt)) {
      onChange(selected.filter((p) => p !== pt));
    } else {
      onChange([...selected, pt]);
    }
  }

  return (
    <div className="flex flex-wrap gap-2">
      {EVALUATION_POINTS.map((ep) => {
        const active = selected.includes(ep.value);
        return (
          <Badge
            key={ep.value}
            variant={active ? "default" : "outline"}
            className="cursor-pointer select-none"
            onClick={() => toggle(ep.value)}
          >
            {ep.label}
          </Badge>
        );
      })}
      {selected.length === 0 && (
        <span className="text-xs text-muted-foreground ml-1">
          (applies to all checkpoints)
        </span>
      )}
    </div>
  );
}

// ── Create Rule Dialog ───────────────────────────────────────────────

function CreateRuleDialog({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [ruleId, setRuleId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [action, setAction] = useState<IBACRuleAction>("deny");
  const [priority, setPriority] = useState(100);
  const [evalPoints, setEvalPoints] = useState<IBACEvaluationPoint[]>([]);
  const [conditions, setConditions] = useState<IBACRuleConditions>({});

  function reset() {
    setRuleId("");
    setName("");
    setDescription("");
    setAction("deny");
    setPriority(100);
    setEvalPoints([]);
    setConditions({});
    setError(null);
  }

  async function handleCreate() {
    setSaving(true);
    setError(null);
    try {
      await createIBACRule({
        rule_id: ruleId,
        name,
        description,
        action,
        priority,
        evaluation_points: evalPoints,
        conditions,
      });
      reset();
      setOpen(false);
      onCreated();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        if (!v) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm">
          <Plus className="mr-2 h-4 w-4" />
          New Rule
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Create IBAC Rule</DialogTitle>
          <DialogDescription>
            Define a guardrail rule that will be evaluated at IBAC checkpoints
            during intent processing. Rules are evaluated in priority order
            (lower number = higher priority).
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="rule-id">Rule ID</Label>
              <Input
                id="rule-id"
                placeholder="no-pii-access"
                value={ruleId}
                onChange={(e) => setRuleId(e.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="rule-name">Name</Label>
              <Input
                id="rule-name"
                placeholder="Block PII access"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="rule-desc">Description</Label>
            <Textarea
              id="rule-desc"
              placeholder="Prevents intents from accessing personally identifiable information…"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label>Action</Label>
              <Select
                value={action}
                onValueChange={(v) => setAction(v as IBACRuleAction)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="deny">Deny</SelectItem>
                  <SelectItem value="allow">Allow</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="rule-priority">Priority</Label>
              <Input
                id="rule-priority"
                type="number"
                value={priority}
                onChange={(e) => setPriority(parseInt(e.target.value, 10) || 100)}
              />
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label>Evaluation Points</Label>
            <EvalPointPicker selected={evalPoints} onChange={setEvalPoints} />
          </div>
          <div className="border-t pt-4">
            <h4 className="text-sm font-medium mb-3">Conditions</h4>
            <ConditionsEditor conditions={conditions} onChange={setConditions} />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">Cancel</Button>
          </DialogClose>
          <Button onClick={handleCreate} disabled={saving || !ruleId || !name}>
            {saving ? "Creating…" : "Create Rule"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Edit Rule Dialog ─────────────────────────────────────────────────

function EditRuleDialog({
  rule,
  onUpdated,
}: {
  rule: IBACRule;
  onUpdated: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState(rule.name);
  const [description, setDescription] = useState(rule.description);
  const [action, setAction] = useState<IBACRuleAction>(rule.action);
  const [priority, setPriority] = useState(rule.priority);
  const [enabled, setEnabled] = useState(rule.enabled);
  const [evalPoints, setEvalPoints] = useState<IBACEvaluationPoint[]>(
    rule.evaluation_points,
  );
  const [conditions, setConditions] = useState<IBACRuleConditions>(
    rule.conditions,
  );

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await updateIBACRule(rule.rule_id, {
        name,
        description,
        action,
        priority,
        enabled,
        evaluation_points: evalPoints,
        conditions,
      });
      setOpen(false);
      onUpdated();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon">
          <Pencil className="h-4 w-4" />
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Edit Rule: {rule.rule_id}</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="edit-name">Name</Label>
              <Input
                id="edit-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="flex items-end gap-2 pb-0.5">
              <input
                type="checkbox"
                id="edit-enabled"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                className="h-4 w-4"
              />
              <Label htmlFor="edit-enabled">Enabled</Label>
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="edit-desc">Description</Label>
            <Textarea
              id="edit-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label>Action</Label>
              <Select
                value={action}
                onValueChange={(v) => setAction(v as IBACRuleAction)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="deny">Deny</SelectItem>
                  <SelectItem value="allow">Allow</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="edit-priority">Priority</Label>
              <Input
                id="edit-priority"
                type="number"
                value={priority}
                onChange={(e) => setPriority(parseInt(e.target.value, 10) || 100)}
              />
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label>Evaluation Points</Label>
            <EvalPointPicker selected={evalPoints} onChange={setEvalPoints} />
          </div>
          <div className="border-t pt-4">
            <h4 className="text-sm font-medium mb-3">Conditions</h4>
            <ConditionsEditor conditions={conditions} onChange={setConditions} />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">Cancel</Button>
          </DialogClose>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? "Saving…" : "Save Changes"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Page ─────────────────────────────────────────────────────────────

export default function IBACRulesPage() {
  const [search, setSearch] = useState("");
  const { data: rules, loading, error, refetch } = useAsync(fetchIBACRules, []);

  const filtered = (rules ?? []).filter(
    (r) =>
      r.rule_id.toLowerCase().includes(search.toLowerCase()) ||
      r.name.toLowerCase().includes(search.toLowerCase()) ||
      r.description.toLowerCase().includes(search.toLowerCase()),
  );

  async function handleDelete(ruleId: string) {
    if (!confirm("Delete this IBAC rule?")) return;
    await deleteIBACRule(ruleId);
    refetch();
  }

  async function handleToggle(rule: IBACRule) {
    await updateIBACRule(rule.rule_id, { enabled: !rule.enabled });
    refetch();
  }

  const enabledCount = (rules ?? []).filter((r) => r.enabled).length;
  const denyCount = (rules ?? []).filter((r) => r.action === "deny" && r.enabled).length;
  const allowCount = (rules ?? []).filter((r) => r.action === "allow" && r.enabled).length;

  return (
    <>
      <AppHeader
        breadcrumbs={[{ label: "Dashboard", href: "/" }, { label: "IBAC Rules" }]}
      />
      <div className="flex flex-1 flex-col gap-4 p-4 pt-0">
        {/* Summary cards */}
        <div className="grid auto-rows-min gap-4 md:grid-cols-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Total Rules</CardTitle>
              <Shield className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{rules?.length ?? "—"}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Active</CardTitle>
              <ShieldCheck className="h-4 w-4 text-green-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{enabledCount}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Deny Rules</CardTitle>
              <ShieldX className="h-4 w-4 text-red-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{denyCount}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">
                Allow Rules
              </CardTitle>
              <ShieldAlert className="h-4 w-4 text-blue-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{allowCount}</div>
            </CardContent>
          </Card>
        </div>

        {/* Toolbar */}
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search rules…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8"
            />
            {search && (
              <button
                className="absolute right-2.5 top-2.5 text-muted-foreground hover:text-foreground"
                onClick={() => setSearch("")}
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
          <CreateRuleDialog onCreated={refetch} />
        </div>

        {/* Table */}
        <Card>
          <CardContent className="p-0">
            {loading ? (
              <div className="flex items-center justify-center py-12 text-muted-foreground">
                Loading…
              </div>
            ) : error ? (
              <div className="flex items-center justify-center py-12 text-destructive">
                {error}
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-12">Prio</TableHead>
                    <TableHead>Rule ID</TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead className="text-center">Action</TableHead>
                    <TableHead>Evaluation Points</TableHead>
                    <TableHead>Conditions</TableHead>
                    <TableHead className="text-center">Status</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.length === 0 ? (
                    <TableRow>
                      <TableCell
                        colSpan={8}
                        className="text-center py-8 text-muted-foreground"
                      >
                        No IBAC rules found. Create one to start enforcing
                        guardrails on intent processing.
                      </TableCell>
                    </TableRow>
                  ) : (
                    filtered.map((r) => {
                      const condSummary = summarizeConditions(r.conditions);
                      return (
                        <TableRow
                          key={r.rule_id}
                          className={!r.enabled ? "opacity-50" : undefined}
                        >
                          <TableCell className="font-mono text-sm text-center">
                            {r.priority}
                          </TableCell>
                          <TableCell className="font-mono text-sm">
                            {r.rule_id}
                          </TableCell>
                          <TableCell>
                            <div>{r.name}</div>
                            {r.description && (
                              <div className="text-xs text-muted-foreground truncate max-w-[200px]">
                                {r.description}
                              </div>
                            )}
                          </TableCell>
                          <TableCell className="text-center">
                            <Badge
                              variant={
                                r.action === "deny" ? "destructive" : "default"
                              }
                            >
                              {r.action.toUpperCase()}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-wrap gap-1">
                              {r.evaluation_points.length === 0 ? (
                                <span className="text-xs text-muted-foreground">
                                  All
                                </span>
                              ) : (
                                r.evaluation_points.map((ep) => (
                                  <Badge
                                    key={ep}
                                    variant="outline"
                                    className="text-xs"
                                  >
                                    {epLabel(ep)}
                                  </Badge>
                                ))
                              )}
                            </div>
                          </TableCell>
                          <TableCell>
                            <div className="text-xs text-muted-foreground max-w-[200px] truncate">
                              {condSummary || "—"}
                            </div>
                          </TableCell>
                          <TableCell className="text-center">
                            <Badge
                              variant={r.enabled ? "default" : "secondary"}
                            >
                              {r.enabled ? "Active" : "Disabled"}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-right">
                            <div className="flex items-center justify-end gap-1">
                              <Button
                                variant="ghost"
                                size="icon"
                                title={
                                  r.enabled ? "Disable rule" : "Enable rule"
                                }
                                onClick={() => handleToggle(r)}
                              >
                                {r.enabled ? (
                                  <ToggleRight className="h-4 w-4 text-green-500" />
                                ) : (
                                  <ToggleLeft className="h-4 w-4 text-muted-foreground" />
                                )}
                              </Button>
                              <EditRuleDialog rule={r} onUpdated={refetch} />
                              <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => handleDelete(r.rule_id)}
                              >
                                <Trash2 className="h-4 w-4 text-destructive" />
                              </Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      );
                    })
                  )}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}

// ── Condition summary helper ─────────────────────────────────────────

function summarizeConditions(c: IBACRuleConditions): string {
  const parts: string[] = [];
  if (c.intent_keywords?.length) parts.push(`keywords: ${c.intent_keywords.join(", ")}`);
  if (c.intent_patterns?.length) parts.push(`patterns: ${c.intent_patterns.length}`);
  if (c.blocked_agents?.length) parts.push(`blocked agents: ${c.blocked_agents.length}`);
  if (c.allowed_agents?.length) parts.push(`allowed agents: ${c.allowed_agents.length}`);
  if (c.blocked_scopes?.length) parts.push(`blocked scopes: ${c.blocked_scopes.join(", ")}`);
  if (c.allowed_scopes?.length) parts.push(`allowed scopes: ${c.allowed_scopes.join(", ")}`);
  if (c.blocked_domains?.length) parts.push(`blocked domains: ${c.blocked_domains.join(", ")}`);
  if (c.allowed_domains?.length) parts.push(`allowed domains: ${c.allowed_domains.join(", ")}`);
  if (c.max_agents != null) parts.push(`max agents: ${c.max_agents}`);
  if (c.require_human_approval) parts.push("human approval required");
  return parts.join("; ");
}
