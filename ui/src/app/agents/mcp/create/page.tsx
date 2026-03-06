"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  Cable,
  ChevronDown,
  ChevronUp,
  Plus,
  Trash2,
} from "lucide-react";

import { AppHeader } from "@/components/app-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { createMCPServer } from "@/lib/api";

// ── Types ────────────────────────────────────────────────────────────

interface EnvEntry {
  key: string;
  value: string;
}

interface AuthHeaderEntry {
  key: string;
  value: string;
}

// ── Page ─────────────────────────────────────────────────────────────

export default function CreateMCPServerPage() {
  const router = useRouter();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── Core fields ──
  const [serverId, setServerId] = useState("");
  const [agentId, setAgentId] = useState("");
  const [serverUrl, setServerUrl] = useState("");
  const [transport, setTransport] = useState("http");
  const [semanticDescription, setSemanticDescription] = useState("");
  const [mode, setMode] = useState("persistent");

  // ── stdio fields ──
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");

  // ── Auth headers ──
  const [authHeaders, setAuthHeaders] = useState<AuthHeaderEntry[]>([]);

  // ── Env vars ──
  const [envVars, setEnvVars] = useState<EnvEntry[]>([]);

  // ── Options ──
  const [activate, setActivate] = useState(true);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // ── Auto-generate agent_id from server_id ──
  const handleServerIdChange = (value: string) => {
    setServerId(value);
    if (!agentId || agentId === `${serverId}-agent`) {
      setAgentId(value ? `${value}-agent` : "");
    }
  };

  // ── Auth header helpers ──
  const addAuthHeader = () => {
    setAuthHeaders((prev) => [...prev, { key: "", value: "" }]);
  };
  const removeAuthHeader = (idx: number) => {
    setAuthHeaders((prev) => prev.filter((_, i) => i !== idx));
  };
  const updateAuthHeader = (
    idx: number,
    field: "key" | "value",
    value: string,
  ) => {
    setAuthHeaders((prev) =>
      prev.map((h, i) => (i === idx ? { ...h, [field]: value } : h)),
    );
  };

  // ── Env var helpers ──
  const addEnvVar = () => {
    setEnvVars((prev) => [...prev, { key: "", value: "" }]);
  };
  const removeEnvVar = (idx: number) => {
    setEnvVars((prev) => prev.filter((_, i) => i !== idx));
  };
  const updateEnvVar = (
    idx: number,
    field: "key" | "value",
    value: string,
  ) => {
    setEnvVars((prev) =>
      prev.map((e, i) => (i === idx ? { ...e, [field]: value } : e)),
    );
  };

  // ── Submit ──
  const handleSubmit = async () => {
    if (!serverId.trim() || !agentId.trim() || !serverUrl.trim()) {
      setError("Server ID, Agent ID, and Server URL are required.");
      return;
    }

    setSaving(true);
    setError(null);

    const authHeadersObj: Record<string, string> = {};
    for (const h of authHeaders) {
      if (h.key.trim()) authHeadersObj[h.key.trim()] = h.value;
    }

    const envObj: Record<string, string> = {};
    for (const e of envVars) {
      if (e.key.trim()) envObj[e.key.trim()] = e.value;
    }

    try {
      await createMCPServer({
        server_id: serverId.trim(),
        agent_id: agentId.trim(),
        server_url: serverUrl.trim(),
        transport,
        semantic_description: semanticDescription.trim() || undefined,
        mode,
        command: command.trim() || undefined,
        args: args.trim()
          ? args.split(",").map((a) => a.trim())
          : undefined,
        auth_headers:
          Object.keys(authHeadersObj).length > 0
            ? authHeadersObj
            : undefined,
        env: Object.keys(envObj).length > 0 ? envObj : undefined,
        activate,
      });
      router.push("/agents");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create MCP server.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <AppHeader
        breadcrumbs={[
          { label: "Dashboard", href: "/" },
          { label: "Agents", href: "/agents" },
          { label: "Connect MCP Server" },
        ]}
      />

      <div className="flex flex-1 flex-col gap-6 p-6">
        {/* Header */}
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => router.back()}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
              <Cable className="h-6 w-6" />
              Connect MCP Server
            </h1>
            <p className="text-muted-foreground">
              Bridge an external MCP server into the Agentic Bus as a virtual
              agent.
            </p>
          </div>
        </div>

        <div className="mx-auto w-full max-w-2xl space-y-6">
          {/* ── Identity ──────────────────────────────────────── */}
          <Card>
            <CardContent className="space-y-4 pt-6">
              <h2 className="text-lg font-semibold">Server Identity</h2>
              <p className="text-sm text-muted-foreground">
                A unique server ID and the agent ID it will appear as on the
                bus.
              </p>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="server-id">Server ID</Label>
                  <Input
                    id="server-id"
                    placeholder="acme-crm-server"
                    value={serverId}
                    onChange={(e) => handleServerIdChange(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="agent-id">Agent ID (on the bus)</Label>
                  <Input
                    id="agent-id"
                    placeholder="acme-crm-server-agent"
                    value={agentId}
                    onChange={(e) => setAgentId(e.target.value)}
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="description">Semantic Description</Label>
                <Textarea
                  id="description"
                  placeholder="CRM tools from Acme Inc — customer lookup, deal pipeline, contact management"
                  value={semanticDescription}
                  onChange={(e) => setSemanticDescription(e.target.value)}
                  rows={2}
                />
                <p className="text-xs text-muted-foreground">
                  Helps the coordinator understand what this server provides
                  during negotiation.
                </p>
              </div>
            </CardContent>
          </Card>

          {/* ── Connection ────────────────────────────────────── */}
          <Card>
            <CardContent className="space-y-4 pt-6">
              <h2 className="text-lg font-semibold">Connection</h2>
              <p className="text-sm text-muted-foreground">
                How to reach the MCP server.
              </p>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="transport">Transport</Label>
                  <Select value={transport} onValueChange={setTransport}>
                    <SelectTrigger id="transport">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="http">HTTP (SSE)</SelectItem>
                      <SelectItem value="stdio">stdio</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="mode">Mode</Label>
                  <Select value={mode} onValueChange={setMode}>
                    <SelectTrigger id="mode">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="persistent">Persistent</SelectItem>
                      <SelectItem value="ephemeral">Ephemeral</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="server-url">Server URL</Label>
                <Input
                  id="server-url"
                  placeholder={
                    transport === "http"
                      ? "http://localhost:3000/mcp"
                      : "http://localhost:3000/sse"
                  }
                  value={serverUrl}
                  onChange={(e) => setServerUrl(e.target.value)}
                />
              </div>

              {transport === "stdio" && (
                <>
                  <Separator />
                  <p className="text-sm text-muted-foreground">
                    For stdio transport, specify the command and arguments to
                    launch the server process.
                  </p>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="command">Command</Label>
                      <Input
                        id="command"
                        placeholder="python"
                        value={command}
                        onChange={(e) => setCommand(e.target.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="args">
                        Arguments{" "}
                        <span className="text-muted-foreground font-normal">
                          (comma-separated)
                        </span>
                      </Label>
                      <Input
                        id="args"
                        placeholder="/path/to/server.py, --port, 3000"
                        value={args}
                        onChange={(e) => setArgs(e.target.value)}
                      />
                    </div>
                  </div>
                </>
              )}
            </CardContent>
          </Card>

          {/* ── Advanced (collapsible) ────────────────────────── */}
          <Card>
            <CardContent className="pt-6">
              <button
                type="button"
                onClick={() => setShowAdvanced(!showAdvanced)}
                className="flex w-full items-center justify-between text-sm font-semibold"
              >
                <span>Advanced Options</span>
                {showAdvanced ? (
                  <ChevronUp className="h-4 w-4 text-muted-foreground" />
                ) : (
                  <ChevronDown className="h-4 w-4 text-muted-foreground" />
                )}
              </button>

              {showAdvanced && (
                <div className="mt-4 space-y-6">
                  {/* Auth Headers */}
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <Label>Authentication Headers</Label>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={addAuthHeader}
                      >
                        <Plus className="mr-1 h-3 w-3" />
                        Add Header
                      </Button>
                    </div>
                    {authHeaders.length === 0 && (
                      <p className="text-xs text-muted-foreground">
                        No auth headers. Click &quot;Add Header&quot; if the MCP
                        server requires authentication.
                      </p>
                    )}
                    {authHeaders.map((h, idx) => (
                      <div key={idx} className="flex items-center gap-2">
                        <Input
                          placeholder="Header name (e.g. Authorization)"
                          value={h.key}
                          onChange={(e) =>
                            updateAuthHeader(idx, "key", e.target.value)
                          }
                          className="flex-1"
                        />
                        <Input
                          placeholder="Value (e.g. Bearer sk-...)"
                          type="password"
                          value={h.value}
                          onChange={(e) =>
                            updateAuthHeader(idx, "value", e.target.value)
                          }
                          className="flex-1"
                        />
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => removeAuthHeader(idx)}
                        >
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
                    ))}
                  </div>

                  <Separator />

                  {/* Env vars */}
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <Label>Environment Variables</Label>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={addEnvVar}
                      >
                        <Plus className="mr-1 h-3 w-3" />
                        Add Variable
                      </Button>
                    </div>
                    {envVars.length === 0 && (
                      <p className="text-xs text-muted-foreground">
                        No env variables. Useful for stdio transport to pass
                        secrets to the subprocess.
                      </p>
                    )}
                    {envVars.map((e, idx) => (
                      <div key={idx} className="flex items-center gap-2">
                        <Input
                          placeholder="Variable name"
                          value={e.key}
                          onChange={(ev) =>
                            updateEnvVar(idx, "key", ev.target.value)
                          }
                          className="flex-1"
                        />
                        <Input
                          placeholder="Value"
                          type="password"
                          value={e.value}
                          onChange={(ev) =>
                            updateEnvVar(idx, "value", ev.target.value)
                          }
                          className="flex-1"
                        />
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => removeEnvVar(idx)}
                        >
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {/* ── Activate toggle & Submit ──────────────────────── */}
          <Card>
            <CardContent className="space-y-4 pt-6">
              <div className="flex items-center justify-between">
                <div>
                  <Label htmlFor="activate">Activate immediately</Label>
                  <p className="text-xs text-muted-foreground">
                    Start the bridge and discover tools right away.
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

          {/* Error */}
          {error && (
            <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center justify-end gap-3">
            <Button
              variant="outline"
              onClick={() => router.back()}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button onClick={handleSubmit} disabled={saving}>
              {saving ? "Connecting…" : "Connect MCP Server"}
            </Button>
          </div>
        </div>
      </div>
    </>
  );
}
