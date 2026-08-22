"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Plus, X, ChevronDown, ChevronUp, Wrench } from "lucide-react";

import { AppHeader } from "@/components/app-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";

import { useAsync } from "@/hooks/use-async";
import { createManagedAgent, fetchAvailableTools } from "@/lib/api";
import type { ToolInfo, ToolRequirement } from "@/lib/types";

// ── Capability inline form ───────────────────────────────────────────

interface OutputFieldDraft {
  name: string;
  type: string;
  description: string;
}

interface CapabilityDraft {
  capability_id: string;
  description: string;
  expected_output: string;
  supported_data_domains: string;
  estimated_cost: string;
  estimated_latency: string;
  output_fields: OutputFieldDraft[];
}

const SUPPORTED_FIELD_TYPES = ["str", "int", "float", "bool", "list", "dict"];

const emptyCapability: CapabilityDraft = {
  capability_id: "",
  description: "",
  expected_output: "",
  supported_data_domains: "",
  estimated_cost: "0",
  estimated_latency: "0",
  output_fields: [],
};

// ── Page ─────────────────────────────────────────────────────────────

export default function CreateManagedAgentPage() {
  const router = useRouter();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── Identity fields ──
  const [agentId, setAgentId] = useState("");
  const [typedName, setTypedName] = useState("");
  const [nameEdited, setNameEdited] = useState(false);

  // ── persona ──
  const [role, setRole] = useState("");
  const [goal, setGoal] = useState("");
  const [backstory, setBackstory] = useState("");

  // ── Agent options ──
  const [verbose, setVerbose] = useState(false);
  const [maxIter, setMaxIter] = useState("25");
  const [maxRpm, setMaxRpm] = useState("");
  const [memory, setMemory] = useState(true);

  // ── Tools ──
  const [selectedTools, setSelectedTools] = useState<string[]>([]);
  const [toolSearch, setToolSearch] = useState("");
  const [toolConfig, setToolConfig] = useState<Record<string, Record<string, string>>>({});

  // ── Capabilities ──
  const [capabilities, setCapabilities] = useState<CapabilityDraft[]>([]);
  const [showCapForm, setShowCapForm] = useState(false);
  const [capDraft, setCapDraft] = useState<CapabilityDraft>({
    ...emptyCapability,
  });

  // ── Status ──
  const [activate, setActivate] = useState(false);

  // ── Sections expand (for compact UX) ──
  const [showOptions, setShowOptions] = useState(false);

  // ── Fetch tools ──
  const { data: availableTools } = useAsync<ToolInfo[]>(
    () => fetchAvailableTools(),
    [],
  );

  const tools = availableTools ?? [];

  const filteredTools = tools.filter(
    (t) =>
      t.name.toLowerCase().includes(toolSearch.toLowerCase()) ||
      t.description.toLowerCase().includes(toolSearch.toLowerCase()),
  );

  function autoName(slug: string) {
    return slug
      .replace(/[-_]/g, " ")
      .replace(/\w/g, (c) => c.toUpperCase());
  }

  // Display name mirrors agent_id until the user types their own. Derived
  // during render rather than synced by an effect: setState inside an effect
  // causes the cascading re-render the React Compiler rules flag, and the
  // old version also referenced autoName before it was declared.
  const name = nameEdited ? typedName : autoName(agentId);

  function onNameChange(value: string) {
    setTypedName(value);
    // Clearing the field hands control back to the generated name.
    setNameEdited(value.trim() !== "");
  }

  function toggleTool(toolName: string) {
    setSelectedTools((prev) => {
      if (prev.includes(toolName)) {
        // Remove tool config when deselecting
        setToolConfig((cfg) => {
          const next = { ...cfg };
          delete next[toolName];
          return next;
        });
        return prev.filter((t) => t !== toolName);
      }
      return [...prev, toolName];
    });
  }

  function updateToolConfigValue(toolName: string, key: string, value: string) {
    setToolConfig((prev) => ({
      ...prev,
      [toolName]: { ...(prev[toolName] || {}), [key]: value },
    }));
  }

  // Build a lookup for tool requirements
  const toolRequirements: Record<string, ToolRequirement[]> = {};
  for (const t of tools) {
    if (t.requirements && t.requirements.length > 0) {
      toolRequirements[t.name] = t.requirements;
    }
  }

  function addCapability() {
    if (!capDraft.capability_id) return;
    setCapabilities((prev) => [...prev, { ...capDraft }]);
    setCapDraft({ ...emptyCapability });
    setShowCapForm(false);
  }

  function removeCapability(idx: number) {
    setCapabilities((prev) => prev.filter((_, i) => i !== idx));
  }

  async function handleCreate() {
    setError(null);
    setSaving(true);
    try {
      await createManagedAgent({
        agent_id: agentId.trim(),
        name: name.trim(),
        role: role.trim(),
        goal: goal.trim(),
        backstory: backstory.trim(),
        verbose,
        max_iter: parseInt(maxIter, 10) || 25,
        max_rpm: maxRpm ? parseInt(maxRpm, 10) : null,
        memory,
        tools: selectedTools,
        tool_config: Object.fromEntries(
          Object.entries(toolConfig).filter(
            ([k]) => selectedTools.includes(k) &&
              Object.values(toolConfig[k] || {}).some((v) => v.trim() !== ""),
          ),
        ),
        capabilities: capabilities.map((c) => ({
          capability_id: c.capability_id,
          description: c.description,
          expected_output: c.expected_output,
          supported_data_domains: c.supported_data_domains
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
          estimated_cost: parseFloat(c.estimated_cost) || 0,
          estimated_latency: parseFloat(c.estimated_latency) || 0,
          output_fields: c.output_fields
            .filter((f) => f.name.trim() !== "")
            .map((f) => ({
              name: f.name.trim(),
              type: f.type || "str",
              description: f.description,
            })),
        })),
        activate,
      });
      router.push("/agents");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  const canSubmit =
    agentId.trim() !== "" &&
    role.trim() !== "" &&
    goal.trim() !== "" &&
    backstory.trim() !== "";

  return (
    <>
      <AppHeader
        breadcrumbs={[
          { label: "Dashboard", href: "/" },
          { label: "Agents", href: "/agents" },
          { label: "Create Managed Agent" },
        ]}
      />

      <div className="flex flex-1 flex-col gap-6 p-6">
        {/* Header */}
        <div className="flex items-center gap-4">
          <Button
            variant="outline"
            size="icon"
            onClick={() => router.push("/agents")}
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
              <Wrench className="h-6 w-6" />
              Create Managed Agent
            </h1>
            <p className="text-muted-foreground">
              Create a new CrewAI-based managed agent using the
              Role-Goal-Backstory framework.
            </p>
          </div>
        </div>

        {/* Form */}
        <div className="mx-auto w-full max-w-3xl space-y-6">
          {/* ── Identity ──────────────────────────────── */}
          <Card>
            <CardContent className="pt-6 space-y-4">
              <h3 className="text-sm font-semibold text-muted-foreground tracking-wide uppercase">
                Identity
              </h3>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="agent-id">Agent ID *</Label>
                  <Input
                    id="agent-id"
                    placeholder="market-researcher-01"
                    value={agentId}
                    onChange={(e) => setAgentId(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    Unique slug identifier
                  </p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="agent-name">Display Name</Label>
                  <Input
                    id="agent-name"
                    placeholder="Market Researcher 01"
                    value={name}
                    onChange={(e) => onNameChange(e.target.value)}
                  />
                </div>
              </div>
            </CardContent>
          </Card>

          {/* ── Persona ─────────────────────────── */}
          <Card>
            <CardContent className="pt-6 space-y-4">
              <h3 className="text-sm font-semibold text-muted-foreground tracking-wide uppercase">
                Persona
              </h3>
              <p className="text-xs text-muted-foreground">
                Be specific and specialised — avoid generic roles.
              </p>
              <div className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="role">Role *</Label>
                  <Input
                    id="role"
                    placeholder="Senior UX Researcher specializing in user interview analysis"
                    value={role}
                    onChange={(e) => setRole(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="goal">Goal *</Label>
                  <Input
                    id="goal"
                    placeholder="Uncover actionable user insights by analyzing interview data"
                    value={goal}
                    onChange={(e) => setGoal(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="backstory">Backstory *</Label>
                  <Textarea
                    id="backstory"
                    placeholder="Give depth to the agent: experience, working style, values…"
                    rows={4}
                    value={backstory}
                    onChange={(e) => setBackstory(e.target.value)}
                  />
                </div>
              </div>
            </CardContent>
          </Card>

          {/* ── Tools ──────────────────────────────────── */}
          <Card>
            <CardContent className="pt-6 space-y-4">
              <h3 className="text-sm font-semibold text-muted-foreground tracking-wide uppercase">
                Tools
              </h3>
              <p className="text-xs text-muted-foreground">
                Bind CrewAI tools to this agent.
              </p>
              {selectedTools.length > 0 && (
                <div className="flex flex-wrap gap-1.5 pb-1">
                  {selectedTools.map((t) => (
                    <Badge
                      key={t}
                      variant="default"
                      className="cursor-pointer gap-1 pr-1"
                      onClick={() => toggleTool(t)}
                    >
                      {t}
                      <X className="h-3 w-3" />
                    </Badge>
                  ))}
                </div>
              )}
              <Input
                placeholder="Search tools…"
                value={toolSearch}
                onChange={(e) => setToolSearch(e.target.value)}
              />
              <div className="max-h-48 overflow-y-auto rounded-md border">
                {filteredTools.length === 0 ? (
                  <p className="p-3 text-sm text-muted-foreground">
                    {tools.length === 0 ? "Loading tools…" : "No tools match."}
                  </p>
                ) : (
                  filteredTools.map((tool) => {
                    const selected = selectedTools.includes(tool.name);
                    return (
                      <button
                        key={tool.name}
                        type="button"
                        className={`flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-accent transition-colors ${
                          selected ? "bg-accent/50" : ""
                        }`}
                        onClick={() => toggleTool(tool.name)}
                      >
                        <div
                          className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                            selected
                              ? "border-primary bg-primary text-primary-foreground"
                              : "border-muted-foreground/30"
                          }`}
                        >
                          {selected && (
                            <svg
                              className="h-3 w-3"
                              fill="none"
                              viewBox="0 0 24 24"
                              stroke="currentColor"
                              strokeWidth={3}
                            >
                              <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                d="M5 13l4 4L19 7"
                              />
                            </svg>
                          )}
                        </div>
                        <div className="min-w-0 flex-1">
                          <span className="font-mono text-xs font-medium">
                            {tool.name}
                          </span>
                          {tool.description && (
                            <p className="truncate text-xs text-muted-foreground">
                              {tool.description}
                            </p>
                          )}
                        </div>
                      </button>
                    );
                  })
                )}
              </div>
            </CardContent>
          </Card>

          {/* ── Tool Configuration ─────────────────────── */}
          {selectedTools.some((t) => (toolRequirements[t]?.length ?? 0) > 0) && (
            <Card>
              <CardContent className="pt-6 space-y-4">
                <h3 className="text-sm font-semibold text-muted-foreground tracking-wide uppercase">
                  Tool Configuration
                </h3>
                <p className="text-xs text-muted-foreground">
                  Some selected tools require API keys or other configuration to work.
                  Values are stored encrypted and injected at runtime.
                </p>
                {selectedTools
                  .filter((t) => (toolRequirements[t]?.length ?? 0) > 0)
                  .map((toolName) => (
                    <div key={toolName} className="space-y-2 rounded-lg border p-3">
                      <span className="font-mono text-xs font-semibold">
                        {toolName}
                      </span>
                      <div className="grid gap-2">
                        {toolRequirements[toolName].map((req) => (
                          <div key={req.key} className="grid grid-cols-[140px_1fr] items-center gap-2">
                            <Label className="text-xs truncate" title={req.label}>
                              {req.label}
                              {req.required && (
                                <span className="text-destructive ml-0.5">*</span>
                              )}
                            </Label>
                            <Input
                              type={req.secret ? "password" : "text"}
                              placeholder={req.hint}
                              className="h-8 text-xs font-mono"
                              value={toolConfig[toolName]?.[req.key] ?? ""}
                              onChange={(e) =>
                                updateToolConfigValue(toolName, req.key, e.target.value)
                              }
                            />
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
              </CardContent>
            </Card>
          )}

          {/* ── Capabilities ───────────────────────────── */}
          <Card>
            <CardContent className="pt-6 space-y-4">
              <h3 className="text-sm font-semibold text-muted-foreground tracking-wide uppercase">
                Capabilities
              </h3>
              <p className="text-xs text-muted-foreground">
                Capabilities define what this agent can do on the bus. You can
                add more later.
              </p>
              {capabilities.length > 0 && (
                <div className="space-y-2">
                  {capabilities.map((cap, i) => (
                    <div
                      key={i}
                      className="flex items-start justify-between rounded-lg border p-3"
                    >
                      <div className="min-w-0 flex-1">
                        <span className="font-mono text-sm font-medium">
                          {cap.capability_id}
                        </span>
                        <p className="text-xs text-muted-foreground">
                          {cap.description}
                        </p>
                        {cap.output_fields.length > 0 && (
                          <div className="mt-1.5 flex flex-wrap gap-1">
                            {cap.output_fields.map((f, fi) => (
                              <Badge key={fi} variant="secondary" className="text-[10px] font-mono">
                                {f.name}: {f.type}
                              </Badge>
                            ))}
                          </div>
                        )}
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 shrink-0 text-destructive hover:text-destructive"
                        onClick={() => removeCapability(i)}
                      >
                        <X className="h-3 w-3" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
              {showCapForm ? (
                <div className="space-y-3 rounded-lg border p-4">
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <Label className="text-xs">Capability ID *</Label>
                      <Input
                        placeholder="market_analysis"
                        value={capDraft.capability_id}
                        onChange={(e) =>
                          setCapDraft((d) => ({
                            ...d,
                            capability_id: e.target.value,
                          }))
                        }
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs">Description</Label>
                      <Input
                        placeholder="Analyse market trends…"
                        value={capDraft.description}
                        onChange={(e) =>
                          setCapDraft((d) => ({
                            ...d,
                            description: e.target.value,
                          }))
                        }
                      />
                    </div>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">
                      Tags (comma-separated)
                    </Label>
                    <Input
                      placeholder="finance, marketing"
                      value={capDraft.supported_data_domains}
                      onChange={(e) =>
                        setCapDraft((d) => ({
                          ...d,
                          supported_data_domains: e.target.value,
                        }))
                      }
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <Label className="text-xs">Estimated Cost ($)</Label>
                      <Input
                        type="number"
                        step="0.01"
                        value={capDraft.estimated_cost}
                        onChange={(e) =>
                          setCapDraft((d) => ({
                            ...d,
                            estimated_cost: e.target.value,
                          }))
                        }
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs">Estimated Latency (s)</Label>
                      <Input
                        type="number"
                        step="0.1"
                        value={capDraft.estimated_latency}
                        onChange={(e) =>
                          setCapDraft((d) => ({
                            ...d,
                            estimated_latency: e.target.value,
                          }))
                        }
                      />
                    </div>
                  </div>

                  {/* ── Expected Output ── */}
                  <div className="space-y-3 rounded-lg border p-3 bg-muted/20">
                    <div>
                      <h4 className="text-xs font-semibold tracking-wide uppercase text-muted-foreground">
                        Expected Output
                      </h4>
                      <p className="text-[10px] text-muted-foreground mt-0.5">
                        Describe what the agent should return, then optionally define the exact JSON fields.
                      </p>
                    </div>

                    <div className="space-y-1">
                      <Label className="text-xs">Output Description</Label>
                      <Input
                        placeholder="A JSON report with market trends and competitor analysis…"
                        value={capDraft.expected_output}
                        onChange={(e) =>
                          setCapDraft((d) => ({
                            ...d,
                            expected_output: e.target.value,
                          }))
                        }
                      />
                      <p className="text-[10px] text-muted-foreground">
                        Natural-language description of what the agent should produce.
                      </p>
                    </div>

                    <Separator />

                    {/* Output JSON Fields */}
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <Label className="text-xs font-semibold">Output JSON Fields</Label>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="h-6 text-[10px]"
                          onClick={() =>
                            setCapDraft((d) => ({
                              ...d,
                              output_fields: [
                                ...d.output_fields,
                                { name: "", type: "str", description: "" },
                              ],
                            }))
                          }
                        >
                          <Plus className="mr-1 h-3 w-3" />
                          Add Field
                        </Button>
                      </div>
                      {capDraft.output_fields.length === 0 && (
                        <p className="text-[10px] text-muted-foreground italic">
                          No fields defined — the agent will return free-form text. Add fields to enforce a JSON schema.
                        </p>
                      )}
                      {capDraft.output_fields.map((field, fi) => (
                        <div key={fi} className="flex items-start gap-2">
                          <div className="flex-1 space-y-1">
                            <Input
                              placeholder="Field name"
                              className="h-7 text-xs"
                              value={field.name}
                              onChange={(e) =>
                                setCapDraft((d) => {
                                  const fields = [...d.output_fields];
                                  fields[fi] = { ...fields[fi], name: e.target.value };
                                  return { ...d, output_fields: fields };
                                })
                              }
                            />
                          </div>
                          <select
                            className="h-7 rounded-md border bg-background px-2 text-xs"
                            value={field.type}
                            onChange={(e) =>
                              setCapDraft((d) => {
                                const fields = [...d.output_fields];
                                fields[fi] = { ...fields[fi], type: e.target.value };
                                return { ...d, output_fields: fields };
                              })
                            }
                          >
                            {SUPPORTED_FIELD_TYPES.map((t) => (
                              <option key={t} value={t}>
                                {t}
                              </option>
                            ))}
                          </select>
                          <div className="flex-1 space-y-1">
                            <Input
                              placeholder="Description (optional)"
                              className="h-7 text-xs"
                              value={field.description}
                              onChange={(e) =>
                                setCapDraft((d) => {
                                  const fields = [...d.output_fields];
                                  fields[fi] = { ...fields[fi], description: e.target.value };
                                  return { ...d, output_fields: fields };
                                })
                              }
                            />
                          </div>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7 shrink-0 text-destructive hover:text-destructive"
                            onClick={() =>
                              setCapDraft((d) => ({
                                ...d,
                                output_fields: d.output_fields.filter((_, i) => i !== fi),
                              }))
                            }
                          >
                            <X className="h-3 w-3" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      onClick={addCapability}
                      disabled={!capDraft.capability_id}
                    >
                      Add
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setShowCapForm(false);
                        setCapDraft({ ...emptyCapability });
                      }}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowCapForm(true)}
                >
                  <Plus className="mr-1.5 h-3.5 w-3.5" />
                  Add Capability
                </Button>
              )}
            </CardContent>
          </Card>

          {/* ── Advanced Options (collapsible) ─────────── */}
          <Card>
            <CardContent className="pt-6 space-y-4">
              <button
                type="button"
                className="flex w-full items-center justify-between text-sm font-semibold text-muted-foreground tracking-wide uppercase"
                onClick={() => setShowOptions(!showOptions)}
              >
                Agent Options
                {showOptions ? (
                  <ChevronUp className="h-4 w-4" />
                ) : (
                  <ChevronDown className="h-4 w-4" />
                )}
              </button>
              {showOptions && (
                <div className="grid grid-cols-2 gap-4">
                  <div className="flex items-center justify-between rounded-lg border p-3">
                    <div>
                      <Label htmlFor="verbose">Verbose</Label>
                      <p className="text-xs text-muted-foreground">
                        Show detailed execution logs
                      </p>
                    </div>
                    <Switch
                      id="verbose"
                      checked={verbose}
                      onCheckedChange={setVerbose}
                    />
                  </div>
                  <div className="flex items-center justify-between rounded-lg border p-3">
                    <div>
                      <Label htmlFor="memory">Memory</Label>
                      <p className="text-xs text-muted-foreground">
                        Enable agent memory
                      </p>
                    </div>
                    <Switch
                      id="memory"
                      checked={memory}
                      onCheckedChange={setMemory}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="max-iter">Max Iterations</Label>
                    <Input
                      id="max-iter"
                      type="number"
                      min={1}
                      value={maxIter}
                      onChange={(e) => setMaxIter(e.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="max-rpm">Max RPM</Label>
                    <Input
                      id="max-rpm"
                      type="number"
                      min={0}
                      placeholder="No limit"
                      value={maxRpm}
                      onChange={(e) => setMaxRpm(e.target.value)}
                    />
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {/* ── Status ─────────────────────────────────── */}
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center justify-between">
                <div>
                  <Label htmlFor="activate">Activate immediately</Label>
                  <p className="text-xs text-muted-foreground">
                    If off, the agent will be created in{" "}
                    <strong>draft</strong> status.
                  </p>
                </div>
                <Switch
                  id="activate"
                  checked={activate}
                  onCheckedChange={setActivate}
                />
              </div>
            </CardContent>
          </Card>

          {/* ── Error ──────────────────────────────────── */}
          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}

          {/* ── Actions ────────────────────────────────── */}
          <div className="flex justify-end gap-3 pb-6">
            <Button
              variant="outline"
              onClick={() => router.push("/agents")}
            >
              Cancel
            </Button>
            <Button
              onClick={handleCreate}
              disabled={saving || !canSubmit}
            >
              {saving ? "Creating…" : "Create Agent"}
            </Button>
          </div>
        </div>
      </div>
    </>
  );
}
