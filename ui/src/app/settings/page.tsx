"use client";

import { useState } from "react";
import {
  Cpu,
  Settings as SettingsIcon,
  Loader2,
  Plus,
  Trash2,
  Pencil,
  Zap,
} from "lucide-react";

import { AppHeader } from "@/components/app-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
  fetchLLMConfigs,
  fetchSettings,
  addLLMConfig,
  updateLLMConfig,
  deleteLLMConfig,
  activateLLMConfig,
} from "@/lib/api";
import type { LLMConfig } from "@/lib/types";

// ── Constants ────────────────────────────────────────────────────────

const PROVIDERS = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "google", label: "Google" },
  { value: "ollama", label: "Ollama" },
  { value: "azure", label: "Azure OpenAI" },
] as const;

const DEFAULT_MODELS: Record<string, string> = {
  openai: "gpt-4o-mini",
  anthropic: "claude-sonnet-4-20250514",
  google: "gemini-2.0-flash",
  ollama: "llama3",
  azure: "gpt-4o-mini",
};

// Provider-specific extra fields definition.
// Each field maps to a key that goes into `extra_config` on the backend.
interface ProviderField {
  key: string;
  label: string;
  placeholder: string;
  hint?: string;
  required?: boolean;
}

const PROVIDER_FIELDS: Record<string, ProviderField[]> = {
  openai: [],
  anthropic: [],
  google: [],
  ollama: [
    {
      key: "base_url",
      label: "Base URL",
      placeholder: "http://localhost:11434",
      hint: "Ollama server address. Defaults to http://localhost:11434.",
    },
  ],
  azure: [
    {
      key: "azure_endpoint",
      label: "Azure Endpoint",
      placeholder: "https://my-resource.openai.azure.com/",
      hint: "Your Azure OpenAI resource endpoint URL.",
      required: true,
    },
    {
      key: "api_version",
      label: "API Version",
      placeholder: "2024-12-01-preview",
      hint: "Azure OpenAI API version. Defaults to 2024-12-01-preview.",
    },
    {
      key: "azure_deployment",
      label: "Deployment Name",
      placeholder: "my-gpt-4o-deployment",
      hint: "Azure deployment name. Defaults to the model name if empty.",
    },
  ],
};

// Whether a provider needs an API key
const PROVIDER_NEEDS_API_KEY: Record<string, boolean> = {
  openai: true,
  anthropic: true,
  google: true,
  ollama: false,
  azure: true,
};

const API_KEY_ENV_HINT: Record<string, string> = {
  openai: "OPENAI_API_KEY",
  anthropic: "ANTHROPIC_API_KEY",
  google: "GOOGLE_API_KEY",
  azure: "AZURE_OPENAI_API_KEY",
};

// ── Helpers ──────────────────────────────────────────────────────────

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "—";
  return new Date(dateStr).toLocaleString();
}

// ── Provider-specific fields component ───────────────────────────────

function ProviderExtraFields({
  provider,
  extraConfig,
  onChange,
  idPrefix,
}: {
  provider: string;
  extraConfig: Record<string, string>;
  onChange: (ec: Record<string, string>) => void;
  idPrefix: string;
}) {
  const fields = PROVIDER_FIELDS[provider] ?? [];
  if (fields.length === 0) return null;

  return (
    <div className="grid gap-3 rounded-md border p-3">
      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
        {PROVIDERS.find((p) => p.value === provider)?.label} Settings
      </p>
      {fields.map((f) => (
        <div key={f.key} className="grid gap-1.5">
          <Label htmlFor={`${idPrefix}-${f.key}`}>
            {f.label}
            {f.required && <span className="text-destructive"> *</span>}
          </Label>
          <Input
            id={`${idPrefix}-${f.key}`}
            placeholder={f.placeholder}
            value={extraConfig[f.key] ?? ""}
            onChange={(e) =>
              onChange({ ...extraConfig, [f.key]: e.target.value })
            }
          />
          {f.hint && (
            <p className="text-xs text-muted-foreground">{f.hint}</p>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Create LLM Config Dialog ─────────────────────────────────────────

function CreateLLMConfigDialog({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState(DEFAULT_MODELS["openai"]);
  const [temperature, setTemperature] = useState("0.0");
  const [apiKey, setApiKey] = useState("");
  const [isCurrent, setIsCurrent] = useState(false);
  const [extraConfig, setExtraConfig] = useState<Record<string, string>>({});

  function reset() {
    setName("");
    setProvider("openai");
    setModel(DEFAULT_MODELS["openai"]);
    setTemperature("0.0");
    setApiKey("");
    setIsCurrent(false);
    setExtraConfig({});
    setError(null);
  }

  /** Strip empty strings from extra_config before sending. */
  function cleanExtra(ec: Record<string, string>): Record<string, string> | null {
    const cleaned = Object.fromEntries(
      Object.entries(ec).filter(([, v]) => v.trim() !== ""),
    );
    return Object.keys(cleaned).length > 0 ? cleaned : null;
  }

  async function handleCreate() {
    if (!name.trim()) {
      setError("Name is required.");
      return;
    }
    // Validate required provider-specific fields
    const fields = PROVIDER_FIELDS[provider] ?? [];
    for (const f of fields) {
      if (f.required && !extraConfig[f.key]?.trim()) {
        setError(`${f.label} is required for ${PROVIDERS.find((p) => p.value === provider)?.label}.`);
        return;
      }
    }
    setSaving(true);
    setError(null);
    try {
      await addLLMConfig({
        name: name.trim(),
        provider,
        model,
        temperature: parseFloat(temperature) || 0.0,
        api_key: apiKey.trim() || null,
        extra_config: cleanExtra(extraConfig),
        is_current: isCurrent,
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
          New Config
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Create LLM Configuration</DialogTitle>
          <DialogDescription>
            Add a new LLM provider configuration. You can activate it later or
            set it as the current active config right away.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <div className="grid gap-1.5">
            <Label htmlFor="llm-name">Name</Label>
            <Input
              id="llm-name"
              placeholder="my-openai-config"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label>Provider</Label>
              <Select
                value={provider}
                onValueChange={(v) => {
                  setProvider(v);
                  setModel(DEFAULT_MODELS[v] ?? "");
                  setExtraConfig({});
                  setApiKey("");
                }}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PROVIDERS.map((p) => (
                    <SelectItem key={p.value} value={p.value}>
                      {p.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="llm-model">Model</Label>
              <Input
                id="llm-model"
                placeholder="gpt-4o-mini"
                value={model}
                onChange={(e) => setModel(e.target.value)}
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="llm-temperature">Temperature</Label>
              <Input
                id="llm-temperature"
                type="number"
                step="0.1"
                min="0"
                max="2"
                value={temperature}
                onChange={(e) => setTemperature(e.target.value)}
              />
            </div>
            <div className="flex items-end gap-2 pb-2">
              <input
                type="checkbox"
                id="llm-is-current"
                checked={isCurrent}
                onChange={(e) => setIsCurrent(e.target.checked)}
                className="h-4 w-4"
              />
              <Label htmlFor="llm-is-current">Set as active</Label>
            </div>
          </div>
          <ProviderExtraFields
            provider={provider}
            extraConfig={extraConfig}
            onChange={setExtraConfig}
            idPrefix="create-llm"
          />
          {PROVIDER_NEEDS_API_KEY[provider] !== false && (
            <div className="grid gap-1.5">
              <Label htmlFor="llm-api-key">
                API Key{" "}
                <span className="text-xs text-muted-foreground">(optional)</span>
              </Label>
              <Input
                id="llm-api-key"
                type="password"
                placeholder="sk-…"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Leave empty to use{" "}
                <code className="rounded bg-muted px-1 py-0.5">
                  {API_KEY_ENV_HINT[provider] ?? "env var"}
                </code>{" "}
                from the environment.
              </p>
            </div>
          )}
        </div>
        {error && (
          <p className="text-sm text-destructive">{error}</p>
        )}
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">Cancel</Button>
          </DialogClose>
          <Button onClick={handleCreate} disabled={saving}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Edit LLM Config Dialog ───────────────────────────────────────────

function EditLLMConfigDialog({
  config,
  onUpdated,
}: {
  config: LLMConfig;
  onUpdated: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [provider, setProvider] = useState(config.provider);
  const [model, setModel] = useState(config.model);
  const [temperature, setTemperature] = useState(String(config.temperature));
  const [apiKey, setApiKey] = useState("");
  const [extraConfig, setExtraConfig] = useState<Record<string, string>>(
    (config.extra_config as Record<string, string>) ?? {},
  );

  function reset() {
    setProvider(config.provider);
    setModel(config.model);
    setTemperature(String(config.temperature));
    setApiKey("");
    setExtraConfig((config.extra_config as Record<string, string>) ?? {});
    setError(null);
  }

  function cleanExtra(ec: Record<string, string>): Record<string, string> | null {
    const cleaned = Object.fromEntries(
      Object.entries(ec).filter(([, v]) => v.trim() !== ""),
    );
    return Object.keys(cleaned).length > 0 ? cleaned : null;
  }

  async function handleUpdate() {
    // Validate required provider-specific fields
    const fields = PROVIDER_FIELDS[provider] ?? [];
    for (const f of fields) {
      if (f.required && !extraConfig[f.key]?.trim()) {
        setError(`${f.label} is required for ${PROVIDERS.find((p) => p.value === provider)?.label}.`);
        return;
      }
    }
    setSaving(true);
    setError(null);
    try {
      await updateLLMConfig(config.name, {
        provider,
        model,
        temperature: parseFloat(temperature) || 0.0,
        api_key: apiKey.trim() || null,
        extra_config: cleanExtra(extraConfig),
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
    <Dialog
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        if (!v) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon" className="h-8 w-8">
          <Pencil className="h-4 w-4" />
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            Edit <span className="font-mono">{config.name}</span>
          </DialogTitle>
          <DialogDescription>
            Update the LLM configuration settings. The name cannot be changed.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label>Provider</Label>
              <Select
                value={provider}
                onValueChange={(v) => {
                  setProvider(v);
                  if (model === DEFAULT_MODELS[provider]) {
                    setModel(DEFAULT_MODELS[v] ?? "");
                  }
                  setExtraConfig({});
                  setApiKey("");
                }}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PROVIDERS.map((p) => (
                    <SelectItem key={p.value} value={p.value}>
                      {p.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="edit-llm-model">Model</Label>
              <Input
                id="edit-llm-model"
                value={model}
                onChange={(e) => setModel(e.target.value)}
              />
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="edit-llm-temperature">Temperature</Label>
            <Input
              id="edit-llm-temperature"
              type="number"
              step="0.1"
              min="0"
              max="2"
              value={temperature}
              onChange={(e) => setTemperature(e.target.value)}
            />
          </div>
          <ProviderExtraFields
            provider={provider}
            extraConfig={extraConfig}
            onChange={setExtraConfig}
            idPrefix="edit-llm"
          />
          {PROVIDER_NEEDS_API_KEY[provider] !== false && (
            <div className="grid gap-1.5">
              <Label htmlFor="edit-llm-api-key">
                API Key{" "}
                <span className="text-xs text-muted-foreground">
                  (leave empty to keep current)
                </span>
              </Label>
              <Input
                id="edit-llm-api-key"
                type="password"
                placeholder="sk-…"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Leave empty to keep the current key, or use{" "}
                <code className="rounded bg-muted px-1 py-0.5">
                  {API_KEY_ENV_HINT[provider] ?? "env var"}
                </code>{" "}
                from the environment.
              </p>
            </div>
          )}
        </div>
        {error && (
          <p className="text-sm text-destructive">{error}</p>
        )}
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">Cancel</Button>
          </DialogClose>
          <Button onClick={handleUpdate} disabled={saving}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Save Changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Delete LLM Config Dialog ─────────────────────────────────────────

function DeleteLLMConfigDialog({
  config,
  onDeleted,
}: {
  config: LLMConfig;
  onDeleted: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDelete() {
    setDeleting(true);
    setError(null);
    try {
      await deleteLLMConfig(config.name);
      setOpen(false);
      onDeleted();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 text-destructive hover:text-destructive"
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete LLM Configuration</DialogTitle>
          <DialogDescription>
            Are you sure you want to delete{" "}
            <span className="font-mono font-medium">{config.name}</span>? This
            action cannot be undone.
            {config.is_current && (
              <span className="mt-2 block font-medium text-destructive">
                ⚠ This is the currently active configuration. Deleting it will
                leave the system without an active LLM config.
              </span>
            )}
          </DialogDescription>
        </DialogHeader>
        {error && (
          <p className="text-sm text-destructive">{error}</p>
        )}
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">Cancel</Button>
          </DialogClose>
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={deleting}
          >
            {deleting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Delete
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Main Page ────────────────────────────────────────────────────────

export default function SettingsPage() {
  const {
    data: configs,
    loading: configsLoading,
    refetch: refetchConfigs,
  } = useAsync(() => fetchLLMConfigs());
  const { data: settings, loading: settingsLoading } = useAsync(() =>
    fetchSettings(),
  );

  const [activating, setActivating] = useState<string | null>(null);

  const isLoading = configsLoading || settingsLoading;

  async function handleActivate(name: string) {
    setActivating(name);
    try {
      await activateLLMConfig(name);
      refetchConfigs();
    } catch {
      // silently ignore – the table will show stale data until next refetch
    } finally {
      setActivating(null);
    }
  }

  return (
    <>
      <AppHeader
        breadcrumbs={[
          { label: "Dashboard", href: "/" },
          { label: "Settings" },
        ]}
      />

      <div className="flex flex-1 flex-col gap-6 p-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
          <p className="text-muted-foreground">
            Coordinator and LLM configuration.
          </p>
        </div>

        {isLoading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading settings…
          </div>
        )}

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="flex items-center gap-2">
              <Cpu className="h-5 w-5" />
              LLM Configurations
            </CardTitle>
            <CreateLLMConfigDialog onCreated={refetchConfigs} />
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Provider</TableHead>
                  <TableHead>Model</TableHead>
                  <TableHead>Temperature</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(configs ?? []).length === 0 && !configsLoading ? (
                  <TableRow>
                    <TableCell
                      colSpan={7}
                      className="py-8 text-center text-muted-foreground"
                    >
                      No LLM configurations yet. Click{" "}
                      <span className="font-medium">New Config</span> to add
                      one.
                    </TableCell>
                  </TableRow>
                ) : (
                  (configs ?? []).map((c) => (
                    <TableRow key={c.name}>
                      <TableCell className="font-mono font-medium">
                        {c.name}
                      </TableCell>
                      <TableCell className="capitalize">{c.provider}</TableCell>
                      <TableCell className="font-mono text-xs">
                        {c.model}
                      </TableCell>
                      <TableCell>{c.temperature}</TableCell>
                      <TableCell>
                        {c.is_current ? (
                          <Badge variant="default">Active</Badge>
                        ) : (
                          <Badge variant="secondary">Inactive</Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {formatDate(c.created_at)}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          {!c.is_current && (
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8"
                              title="Set as active"
                              disabled={activating === c.name}
                              onClick={() => handleActivate(c.name)}
                            >
                              {activating === c.name ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <Zap className="h-4 w-4" />
                              )}
                            </Button>
                          )}
                          <EditLLMConfigDialog
                            config={c}
                            onUpdated={refetchConfigs}
                          />
                          <DeleteLLMConfigDialog
                            config={c}
                            onDeleted={refetchConfigs}
                          />
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <SettingsIcon className="h-5 w-5" />
              Coordinator
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <p className="text-muted-foreground">Host</p>
                <p className="font-mono">
                  {settings
                    ? `${settings.host}:${settings.port}`
                    : "—"}
                </p>
              </div>
              <div>
                <p className="text-muted-foreground">Protocol</p>
                <p className="font-mono">WebSocket (Agentic Bus Envelope)</p>
              </div>
              <div>
                <p className="text-muted-foreground">Auto-approve</p>
                <p>{settings?.auto_approve ? "Enabled" : "Disabled"}</p>
              </div>
              <div>
                <p className="text-muted-foreground">OIDC</p>
                <p>
                  {settings?.oidc_enabled
                    ? settings.oidc_issuer
                    : "Disabled (dev mode)"}
                </p>
              </div>
              <div>
                <p className="text-muted-foreground">Database</p>
                <p className="font-mono truncate max-w-[300px]" title={settings?.database_url}>
                  {settings?.database_url ?? "—"}
                </p>
              </div>
              <div>
                <p className="text-muted-foreground">Telemetry</p>
                <p>OpenTelemetry (Console exporter)</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
