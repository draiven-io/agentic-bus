// ---------------------------------------------------------------------------
// Domain types mirroring the Agentic Bus backend models
// ---------------------------------------------------------------------------

export type AgentStatus = "pending" | "approved" | "rejected" | "revoked";
export type ManagedAgentStatus = "draft" | "active" | "disabled";
export type EphemeralAgentStatus = "online";

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
  tool_config: Record<string, Record<string, string>>;
  status: ManagedAgentStatus;
  capabilities: ManagedAgentCapability[];
  created_at: string;
  updated_at: string;
  created_by: string;
}

export interface OutputField {
  name: string;
  type: string;
  description?: string;
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
  output_fields: OutputField[];
  output_schema: Record<string, unknown>;
}

export interface ToolRequirement {
  key: string;
  env: string;
  label: string;
  required: boolean;
  secret: boolean;
  hint: string;
}

export interface ToolInfo {
  name: string;
  description: string;
  requirements: ToolRequirement[];
}

export interface ManagedAgentCreatePayload {
  agent_id: string;
  name: string;
  role: string;
  goal: string;
  backstory: string;
  llm_config_name?: string | null;
  verbose?: boolean;
  max_iter?: number;
  max_rpm?: number | null;
  memory?: boolean;
  tools?: string[];
  tool_config?: Record<string, Record<string, string>>;
  capabilities?: {
    capability_id: string;
    description: string;
    expected_output?: string;
    supported_data_domains?: string[];
    estimated_cost?: number;
    estimated_latency?: number;
    output_fields?: OutputField[];
  }[];
  activate?: boolean;
}

export interface EphemeralAgent {
  agent_id: string;
  version: string;
  status: EphemeralAgentStatus;
  semantic_description: string;
  capabilities: AgentCapability[];
  required_scopes: string[];
  supported_domains: string[];
  operational_constraints: Record<string, unknown>;
  registered_at: string;
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
  target_type: "agent" | "session" | "llm_config" | "ibac_rule" | "system";
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
  ephemeral_agents: number;
  active_sessions: number;
  total_sessions_today: number;
  llm_provider: string;
  llm_model: string;
}

// ---------------------------------------------------------------------------
// Tenants
// ---------------------------------------------------------------------------

export interface Tenant {
  id: number;
  slug: string;
  name: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  user_count: number;
  agent_count: number;
}

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------

export type UserRole = "admin" | "user";

export interface User {
  id: number;
  subject: string;
  email: string;
  display_name: string;
  role: UserRole;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  created_by: string;
  tenant_ids: number[];
  tenant_slugs: string[];
}

// ---------------------------------------------------------------------------
// Current user context
// ---------------------------------------------------------------------------

export interface CurrentUser {
  subject: string;
  email: string;
  display_name: string;
  role: string;
  is_admin: boolean;
  tenant_ids: number[];
  tenant_slugs: string[];
}

// ---------------------------------------------------------------------------
// IBAC Rules
// ---------------------------------------------------------------------------

export type IBACRuleAction = "deny" | "allow";

export type IBACEvaluationPoint =
  | "intent_admission"
  | "offer_eligibility"
  | "negotiation_acceptance"
  | "execution_authorization"
  | "artifact_emission";

export interface IBACRule {
  id: number;
  rule_id: string;
  name: string;
  description: string;
  enabled: boolean;
  priority: number;
  action: IBACRuleAction;
  evaluation_points: IBACEvaluationPoint[];
  conditions: IBACRuleConditions;
  created_at: string;
  updated_at: string;
  created_by: string;
}

export interface IBACRuleConditions {
  intent_keywords?: string[];
  intent_patterns?: string[];
  blocked_agents?: string[];
  allowed_agents?: string[];
  blocked_scopes?: string[];
  allowed_scopes?: string[];
  blocked_domains?: string[];
  allowed_domains?: string[];
  max_agents?: number;
  require_human_approval?: boolean;
}

export interface IBACRuleCreatePayload {
  rule_id: string;
  name: string;
  description?: string;
  enabled?: boolean;
  priority?: number;
  action?: IBACRuleAction;
  evaluation_points?: IBACEvaluationPoint[];
  conditions?: IBACRuleConditions;
}

export interface IBACRuleUpdatePayload {
  name?: string;
  description?: string;
  enabled?: boolean;
  priority?: number;
  action?: IBACRuleAction;
  evaluation_points?: IBACEvaluationPoint[];
  conditions?: IBACRuleConditions;
}
