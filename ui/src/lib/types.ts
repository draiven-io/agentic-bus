// ---------------------------------------------------------------------------
// Domain types mirroring the Agentic Bus backend models
// ---------------------------------------------------------------------------

export type AgentStatus = "pending" | "approved" | "rejected" | "revoked";
export type ManagedAgentStatus = "draft" | "active" | "disabled";

export interface PersistentAgent {
  agent_id: string;
  public_key_pem: string;
  status: AgentStatus;
  semantic_description: string;
  version: string;
  capabilities: AgentCapability[];
  required_scopes: string[];
  supported_domains: string[];
  enrolled_at: string;
  approved_at: string | null;
  approved_by: string | null;
  last_connected_at: string | null;
}

export interface AgentCapability {
  capability_id: string;
  description: string;
  expected_output?: string;
  required_scopes?: string[];
  supported_data_domains?: string[];
  estimated_cost?: number;
  estimated_latency?: number;
}

export interface ManagedAgent {
  id: number;
  agent_id: string;
  name: string;
  role: string;
  goal: string;
  backstory: string;
  llm_config_name: string | null;
  verbose: boolean;
  max_iter: number;
  max_rpm: number | null;
  memory: boolean;
  tools: string[];
  status: ManagedAgentStatus;
  capabilities: ManagedAgentCapability[];
  created_at: string;
  updated_at: string;
  created_by: string;
}

export interface ManagedAgentCapability {
  id: number;
  capability_id: string;
  description: string;
  expected_output: string;
  required_scopes: string[];
  supported_data_domains: string[];
  estimated_cost: number;
  estimated_latency: number;
}

export interface LLMConfig {
  id: number;
  name: string;
  provider: string;
  model: string;
  temperature: number;
  is_current: boolean;
  created_at: string;
  updated_at: string;
  created_by: string;
}

export interface SessionInfo {
  session_id: string;
  phase: string;
  requester_id: string;
  discovered_agents: string[];
  accepted_offers: string[];
  created_at: string;
  dissolved_at: string | null;
}

export interface AuditLogEntry {
  id: string;
  timestamp: string;
  action: string;
  actor: string;
  target: string;
  target_type: "agent" | "session" | "llm_config" | "system";
  details: string;
  severity: "info" | "warning" | "error" | "critical";
}

// ---------------------------------------------------------------------------
// Dashboard stats
// ---------------------------------------------------------------------------

export interface DashboardStats {
  total_agents: number;
  approved_agents: number;
  pending_agents: number;
  managed_agents: number;
  active_sessions: number;
  total_sessions_today: number;
  llm_provider: string;
  llm_model: string;
}
