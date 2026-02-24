// ---------------------------------------------------------------------------
// API client – replaces mock-data with real backend calls
// ---------------------------------------------------------------------------
//
// All requests target /api/admin/* and are proxied by next.config.ts to the
// coordinator's REST API (AGBUS_API_PORT, default 8766).
//
// When OIDC is enabled the caller must pass a Bearer token via the `token`
// option.  In dev mode the backend accepts unauthenticated requests.
// ---------------------------------------------------------------------------

import type {
  AuditLogEntry,
  CurrentUser,
  DashboardStats,
  EphemeralAgent,
  IBACRule,
  IBACRuleCreatePayload,
  IBACRuleUpdatePayload,
  LLMConfig,
  ManagedAgent,
  ManagedAgentCreatePayload,
  PersistentAgent,
  SessionArchiveDetail,
  SessionArchiveListItem,
  SessionInfo,
  Tenant,
  ToolInfo,
  User,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface FetchOptions {
  token?: string;
}

async function apiFetch<T>(
  path: string,
  init?: RequestInit,
  opts?: FetchOptions,
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string>),
  };

  if (opts?.token) {
    headers["Authorization"] = `Bearer ${opts.token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }

  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

export async function fetchDashboardStats(
  opts?: FetchOptions,
): Promise<DashboardStats> {
  return apiFetch<DashboardStats>("/api/admin/stats", undefined, opts);
}

// ---------------------------------------------------------------------------
// Persistent Agents
// ---------------------------------------------------------------------------

export async function fetchPersistentAgents(
  status?: string,
  opts?: FetchOptions,
): Promise<PersistentAgent[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiFetch<PersistentAgent[]>(
    `/api/admin/agents/persistent${qs}`,
    undefined,
    opts,
  );
}

export async function fetchPersistentAgent(
  agentId: string,
  opts?: FetchOptions,
): Promise<PersistentAgent> {
  return apiFetch<PersistentAgent>(
    `/api/admin/agents/persistent/${encodeURIComponent(agentId)}`,
    undefined,
    opts,
  );
}

export async function approveAgent(
  agentId: string,
  opts?: FetchOptions,
): Promise<PersistentAgent> {
  return apiFetch<PersistentAgent>(
    `/api/admin/agents/persistent/${encodeURIComponent(agentId)}/approve`,
    { method: "POST" },
    opts,
  );
}

export async function rejectAgent(
  agentId: string,
  opts?: FetchOptions,
): Promise<PersistentAgent> {
  return apiFetch<PersistentAgent>(
    `/api/admin/agents/persistent/${encodeURIComponent(agentId)}/reject`,
    { method: "POST" },
    opts,
  );
}

export async function revokeAgent(
  agentId: string,
  opts?: FetchOptions,
): Promise<PersistentAgent> {
  return apiFetch<PersistentAgent>(
    `/api/admin/agents/persistent/${encodeURIComponent(agentId)}/revoke`,
    { method: "POST" },
    opts,
  );
}

export async function deletePersistentAgent(
  agentId: string,
  opts?: FetchOptions,
): Promise<void> {
  await apiFetch(
    `/api/admin/agents/persistent/${encodeURIComponent(agentId)}`,
    { method: "DELETE" },
    opts,
  );
}

// ---------------------------------------------------------------------------
// Managed Agents
// ---------------------------------------------------------------------------

export async function fetchManagedAgents(
  status?: string,
  opts?: FetchOptions,
): Promise<ManagedAgent[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiFetch<ManagedAgent[]>(
    `/api/admin/agents/managed${qs}`,
    undefined,
    opts,
  );
}

export async function fetchManagedAgent(
  agentId: string,
  opts?: FetchOptions,
): Promise<ManagedAgent> {
  return apiFetch<ManagedAgent>(
    `/api/admin/agents/managed/${encodeURIComponent(agentId)}`,
    undefined,
    opts,
  );
}

export async function activateManagedAgent(
  agentId: string,
  opts?: FetchOptions,
): Promise<ManagedAgent> {
  return apiFetch<ManagedAgent>(
    `/api/admin/agents/managed/${encodeURIComponent(agentId)}/activate`,
    { method: "POST" },
    opts,
  );
}

export async function disableManagedAgent(
  agentId: string,
  opts?: FetchOptions,
): Promise<ManagedAgent> {
  return apiFetch<ManagedAgent>(
    `/api/admin/agents/managed/${encodeURIComponent(agentId)}/disable`,
    { method: "POST" },
    opts,
  );
}

export async function deleteManagedAgent(
  agentId: string,
  opts?: FetchOptions,
): Promise<void> {
  await apiFetch(
    `/api/admin/agents/managed/${encodeURIComponent(agentId)}`,
    { method: "DELETE" },
    opts,
  );
}

export async function createManagedAgent(
  body: ManagedAgentCreatePayload,
  opts?: FetchOptions,
): Promise<ManagedAgent> {
  return apiFetch<ManagedAgent>(
    "/api/admin/agents/managed",
    { method: "POST", body: JSON.stringify(body) },
    opts,
  );
}

export async function fetchAvailableTools(
  opts?: FetchOptions,
): Promise<ToolInfo[]> {
  return apiFetch<ToolInfo[]>("/api/admin/agents/tools", undefined, opts);
}

// ---------------------------------------------------------------------------
// Ephemeral Agents
// ---------------------------------------------------------------------------

export async function fetchEphemeralAgents(
  opts?: FetchOptions,
): Promise<EphemeralAgent[]> {
  return apiFetch<EphemeralAgent[]>(
    "/api/admin/agents/ephemeral",
    undefined,
    opts,
  );
}

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

export async function fetchSessions(
  opts?: FetchOptions,
): Promise<SessionInfo[]> {
  return apiFetch<SessionInfo[]>("/api/admin/sessions", undefined, opts);
}

// ---------------------------------------------------------------------------
// Audit Log
// ---------------------------------------------------------------------------

export async function fetchAuditLog(
  opts?: FetchOptions,
): Promise<AuditLogEntry[]> {
  return apiFetch<AuditLogEntry[]>("/api/admin/audit", undefined, opts);
}

// ---------------------------------------------------------------------------
// LLM Configurations
// ---------------------------------------------------------------------------

export async function fetchLLMConfigs(
  opts?: FetchOptions,
): Promise<LLMConfig[]> {
  return apiFetch<LLMConfig[]>("/api/admin/llm/configs", undefined, opts);
}

export async function addLLMConfig(
  body: {
    name: string;
    provider: string;
    model: string;
    temperature?: number;
    api_key?: string | null;
    extra_config?: Record<string, unknown> | null;
    is_current?: boolean;
  },
  opts?: FetchOptions,
): Promise<LLMConfig> {
  return apiFetch<LLMConfig>(
    "/api/admin/llm/configs",
    { method: "POST", body: JSON.stringify(body) },
    opts,
  );
}

export async function activateLLMConfig(
  name: string,
  opts?: FetchOptions,
): Promise<LLMConfig> {
  return apiFetch<LLMConfig>(
    `/api/admin/llm/configs/${encodeURIComponent(name)}/activate`,
    { method: "POST" },
    opts,
  );
}

export async function updateLLMConfig(
  name: string,
  body: {
    provider?: string;
    model?: string;
    temperature?: number;
    api_key?: string | null;
    extra_config?: Record<string, unknown> | null;
  },
  opts?: FetchOptions,
): Promise<LLMConfig> {
  return apiFetch<LLMConfig>(
    `/api/admin/llm/configs/${encodeURIComponent(name)}`,
    { method: "PUT", body: JSON.stringify(body) },
    opts,
  );
}

export async function deleteLLMConfig(
  name: string,
  opts?: FetchOptions,
): Promise<void> {
  await apiFetch(
    `/api/admin/llm/configs/${encodeURIComponent(name)}`,
    { method: "DELETE" },
    opts,
  );
}

// ---------------------------------------------------------------------------
// Coordinator Settings
// ---------------------------------------------------------------------------

export interface CoordinatorSettings {
  host: string;
  port: number;
  oidc_enabled: boolean;
  oidc_issuer: string;
  oidc_audience: string;
  auto_approve: boolean;
  database_url: string;
}

export async function fetchSettings(
  opts?: FetchOptions,
): Promise<CoordinatorSettings> {
  return apiFetch<CoordinatorSettings>(
    "/api/admin/settings",
    undefined,
    opts,
  );
}

// ---------------------------------------------------------------------------
// Current User
// ---------------------------------------------------------------------------

export async function fetchCurrentUser(
  opts?: FetchOptions,
): Promise<CurrentUser> {
  return apiFetch<CurrentUser>("/api/admin/me", undefined, opts);
}

// ---------------------------------------------------------------------------
// Tenants
// ---------------------------------------------------------------------------

export async function fetchTenants(
  opts?: FetchOptions,
): Promise<Tenant[]> {
  return apiFetch<Tenant[]>("/api/admin/tenants", undefined, opts);
}

export async function fetchTenant(
  tenantId: number,
  opts?: FetchOptions,
): Promise<Tenant> {
  return apiFetch<Tenant>(
    `/api/admin/tenants/${tenantId}`,
    undefined,
    opts,
  );
}

export async function createTenant(
  body: { slug: string; name: string; enabled?: boolean },
  opts?: FetchOptions,
): Promise<Tenant> {
  return apiFetch<Tenant>(
    "/api/admin/tenants",
    { method: "POST", body: JSON.stringify(body) },
    opts,
  );
}

export async function updateTenant(
  tenantId: number,
  body: { name?: string; enabled?: boolean },
  opts?: FetchOptions,
): Promise<Tenant> {
  return apiFetch<Tenant>(
    `/api/admin/tenants/${tenantId}`,
    { method: "PUT", body: JSON.stringify(body) },
    opts,
  );
}

export async function deleteTenant(
  tenantId: number,
  opts?: FetchOptions,
): Promise<void> {
  await apiFetch(
    `/api/admin/tenants/${tenantId}`,
    { method: "DELETE" },
    opts,
  );
}

export async function assignAgentToTenant(
  tenantId: number,
  agentId: string,
  opts?: FetchOptions,
): Promise<void> {
  await apiFetch(
    `/api/admin/tenants/${tenantId}/agents/${encodeURIComponent(agentId)}`,
    { method: "POST" },
    opts,
  );
}

export async function unassignAgentFromTenant(
  tenantId: number,
  agentId: string,
  opts?: FetchOptions,
): Promise<void> {
  await apiFetch(
    `/api/admin/tenants/${tenantId}/agents/${encodeURIComponent(agentId)}`,
    { method: "DELETE" },
    opts,
  );
}

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------

export async function fetchUsers(
  opts?: FetchOptions,
): Promise<User[]> {
  return apiFetch<User[]>("/api/admin/users", undefined, opts);
}

export async function fetchUser(
  userId: number,
  opts?: FetchOptions,
): Promise<User> {
  return apiFetch<User>(
    `/api/admin/users/${userId}`,
    undefined,
    opts,
  );
}

export async function createUser(
  body: {
    subject: string;
    email?: string;
    display_name?: string;
    role?: string;
    enabled?: boolean;
    tenant_ids?: number[];
  },
  opts?: FetchOptions,
): Promise<User> {
  return apiFetch<User>(
    "/api/admin/users",
    { method: "POST", body: JSON.stringify(body) },
    opts,
  );
}

export async function updateUser(
  userId: number,
  body: {
    email?: string;
    display_name?: string;
    role?: string;
    enabled?: boolean;
    tenant_ids?: number[];
  },
  opts?: FetchOptions,
): Promise<User> {
  return apiFetch<User>(
    `/api/admin/users/${userId}`,
    { method: "PUT", body: JSON.stringify(body) },
    opts,
  );
}

export async function deleteUser(
  userId: number,
  opts?: FetchOptions,
): Promise<void> {
  await apiFetch(
    `/api/admin/users/${userId}`,
    { method: "DELETE" },
    opts,
  );
}

// ---------------------------------------------------------------------------
// IBAC Rules
// ---------------------------------------------------------------------------

export async function fetchIBACRules(
  opts?: FetchOptions,
): Promise<IBACRule[]> {
  return apiFetch<IBACRule[]>("/api/admin/ibac/rules", undefined, opts);
}

export async function fetchIBACRule(
  ruleId: string,
  opts?: FetchOptions,
): Promise<IBACRule> {
  return apiFetch<IBACRule>(
    `/api/admin/ibac/rules/${encodeURIComponent(ruleId)}`,
    undefined,
    opts,
  );
}

export async function createIBACRule(
  body: IBACRuleCreatePayload,
  opts?: FetchOptions,
): Promise<IBACRule> {
  return apiFetch<IBACRule>(
    "/api/admin/ibac/rules",
    { method: "POST", body: JSON.stringify(body) },
    opts,
  );
}

export async function updateIBACRule(
  ruleId: string,
  body: IBACRuleUpdatePayload,
  opts?: FetchOptions,
): Promise<IBACRule> {
  return apiFetch<IBACRule>(
    `/api/admin/ibac/rules/${encodeURIComponent(ruleId)}`,
    { method: "PUT", body: JSON.stringify(body) },
    opts,
  );
}

export async function deleteIBACRule(
  ruleId: string,
  opts?: FetchOptions,
): Promise<void> {
  await apiFetch(
    `/api/admin/ibac/rules/${encodeURIComponent(ruleId)}`,
    { method: "DELETE" },
    opts,
  );
}

// ---------------------------------------------------------------------------
// Session Archives (History)
// ---------------------------------------------------------------------------

export async function fetchSessionArchives(
  opts?: FetchOptions & { limit?: number; offset?: number; outcome?: string },
): Promise<SessionArchiveListItem[]> {
  const params = new URLSearchParams();
  if (opts?.limit) params.set("limit", String(opts.limit));
  if (opts?.offset) params.set("offset", String(opts.offset));
  if (opts?.outcome) params.set("outcome", opts.outcome);
  const qs = params.toString();
  return apiFetch<SessionArchiveListItem[]>(
    `/api/admin/history${qs ? `?${qs}` : ""}`,
    undefined,
    opts,
  );
}

export async function fetchSessionArchive(
  sessionId: string,
  opts?: FetchOptions,
): Promise<SessionArchiveDetail> {
  return apiFetch<SessionArchiveDetail>(
    `/api/admin/history/${encodeURIComponent(sessionId)}`,
    undefined,
    opts,
  );
}

export async function deleteSessionArchive(
  sessionId: string,
  opts?: FetchOptions,
): Promise<void> {
  await apiFetch(
    `/api/admin/history/${encodeURIComponent(sessionId)}`,
    { method: "DELETE" },
    opts,
  );
}
