// ---------------------------------------------------------------------------
// Agentic Bus protocol types for the frontend
// ---------------------------------------------------------------------------
//
// Mirrors the Python envelope.py types used by the coordinator WebSocket.
// The browser connects directly to ws://localhost:8765 as a requester.
// ---------------------------------------------------------------------------

export type MessageType =
  | "intent"
  | "offer"
  | "accept"
  | "reject"
  | "execute"
  | "complete"
  | "dissolve";

export type SenderKind = "requester" | "coordinator" | "agent";

export interface SenderInfo {
  kind: SenderKind;
  id: string;
  oidc_subject?: string;
}

export interface TraceContext {
  trace_id?: string;
  span_id?: string;
}

export interface AgBusEnvelope {
  message_id: string;
  session_id: string;
  message_type: MessageType;
  timestamp: string;
  sender: SenderInfo;
  trace: TraceContext;
  payload: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Typed payloads
// ---------------------------------------------------------------------------

export interface IntentPayload {
  intent_text: string;
  context: Record<string, unknown>;
  requested_outputs: string[];
  ibac_claims_requested: string[];
}

export interface OfferPayload {
  capability_id: string;
  capability_description: string;
  constraints: Record<string, unknown>;
  expected_artifacts: string[];
  estimated_cost: number | null;
  estimated_latency: number | null;
  required_scopes: string[];
  output_schema: Record<string, unknown>;
  composition_plan: Record<string, unknown>;
  participating_agents: string[];
}

export interface AcceptPayload {
  accepted_offers: string[];
  composition_plan: Record<string, unknown>;
  constraints: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  approval_note: string;
}

export interface RejectPayload {
  rejected_offers: string[];
  reason: string;
  renegotiation_hint: Record<string, unknown>;
  renegotiate: boolean;
}

export interface CompletePayload {
  status: "success" | "error" | "partial_failure" | "denied";
  artifacts: Record<string, unknown>[];
  metadata: Record<string, unknown>;
}

export interface DissolvePayload {
  reason: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

let _counter = 0;

export function makeEnvelope(
  messageType: MessageType,
  sessionId: string,
  sender: SenderInfo,
  payload: Record<string, unknown>,
): AgBusEnvelope {
  return {
    message_id: crypto.randomUUID?.() ?? `ui-${Date.now()}-${++_counter}`,
    session_id: sessionId,
    message_type: messageType,
    timestamp: new Date().toISOString(),
    sender,
    trace: {},
    payload,
  };
}
