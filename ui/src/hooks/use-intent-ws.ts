"use client";

import { useCallback, useRef, useState } from "react";
import type {
  AgBusEnvelope,
  MessageType,
  OfferPayload,
  EventPayload,
  SenderInfo,
} from "@/lib/protocol";
import { makeEnvelope } from "@/lib/protocol";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ConnectionStatus =
  | "disconnected"
  | "connecting"
  | "connected"
  | "error";

export type PlanAction = "approve" | "reject" | "renegotiate";

export type SessionPhase =
  | "idle"
  | "created"
  | "intent_admission"
  | "intent_received"
  | "decomposition"
  | "discovery"
  | "negotiation"
  | "plan_proposed"
  | "approved"
  | "execution"
  | "validation"
  | "complete"
  | "dissolution"
  | "error";

export interface TimelineEvent {
  id: string;
  timestamp: string;
  category:
    | "user"
    | "phase"
    | "ibac"
    | "discovery"
    | "negotiation"
    | "execution"
    | "validation"
    | "agent"
    | "warning"
    | "error"
    | "system"
    | "complete"
    | "dissolve";
  phase: SessionPhase;
  summary: string;
  detail?: Record<string, unknown>;
  agentId?: string;
  progress?: number;
  envelope?: AgBusEnvelope;
}

export interface FlowAgent {
  agentId: string;
  capabilityId?: string;
  description?: string;
  suitabilityScore?: number;
  status:
    | "discovered"
    | "offered"
    | "accepted"
    | "rejected"
    | "executing"
    | "completed"
    | "error";
  estimatedCost?: number;
  estimatedLatency?: number;
  outputSchema?: Record<string, unknown>;
  qualityScore?: number;
  qualityRationale?: string;
  latencyMs?: number;
  retries?: number;
}

export interface ExecutionPlan {
  steps: {
    agentId: string;
    capabilityId: string;
    description: string;
    constraints?: Record<string, unknown>;
    outputSchema?: Record<string, unknown>;
  }[];
  viable: boolean;
  participatingAgents: string[];
  flowDescription: string;
  compositionPlan?: Record<string, unknown>;
  mergedOutputSchema?: Record<string, unknown>;
}

export interface ExecutionResult {
  status: "success" | "error" | "partial_failure" | "denied";
  artifacts: Record<string, unknown>[];
  metadata: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8765";

export function useIntentWs() {
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [currentPhase, setCurrentPhase] = useState<SessionPhase>("idle");
  const [progress, setProgress] = useState(0);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [agents, setAgents] = useState<Map<string, FlowAgent>>(new Map());
  const [plan, setPlan] = useState<ExecutionPlan | null>(null);
  const [awaitingApproval, setAwaitingApproval] = useState(false);
  const [result, setResult] = useState<ExecutionResult | null>(null);
  const [intentText, setIntentText] = useState<string>("");
  const [decomposition, setDecomposition] = useState<Record<string, unknown> | null>(null);
  const [assignedAgentId, setAssignedAgentId] = useState<string>("");

  const wsRef = useRef<WebSocket | null>(null);
  const senderRef = useRef<SenderInfo>({
    kind: "requester",
    id: `ui-${Date.now().toString(36)}`,
    oidc_subject: "",
  });

  const addEvent = useCallback((evt: TimelineEvent) => {
    setEvents((prev) => [...prev, evt]);
    if (evt.progress != null) setProgress(evt.progress);
  }, []);

  const updateAgent = useCallback(
    (agentId: string, update: Partial<FlowAgent>) => {
      setAgents((prev) => {
        const next = new Map(prev);
        const existing = next.get(agentId) || {
          agentId,
          status: "discovered" as const,
        };
        next.set(agentId, { ...existing, ...update });
        return next;
      });
    },
    [],
  );

  const handleEnvelope = useCallback(
    (envelope: AgBusEnvelope) => {
      const ts = envelope.timestamp;
      const id = envelope.message_id;

      if (envelope.session_id) {
        setSessionId(envelope.session_id);
      }

      switch (envelope.message_type as MessageType) {
        case "offer": {
          const payload = envelope.payload as unknown as OfferPayload;
          if (payload.capability_id === "__composed_plan__") {
            const steps =
              (payload.composition_plan?.steps as {
                agent_id: string;
                capability_id: string;
                description: string;
                constraints?: Record<string, unknown>;
                output_schema?: Record<string, unknown>;
              }[]) || [];
            const execPlan: ExecutionPlan = {
              steps: steps.map((s) => ({
                agentId: s.agent_id,
                capabilityId: s.capability_id,
                description: s.description,
                constraints: s.constraints,
                outputSchema: s.output_schema,
              })),
              viable: true,
              participatingAgents: payload.participating_agents || [],
              flowDescription: payload.capability_description || "",
              compositionPlan: payload.composition_plan,
              mergedOutputSchema: payload.output_schema,
            };
            setPlan(execPlan);
            setAwaitingApproval(true);
            setCurrentPhase("plan_proposed");

            for (const step of steps) {
              updateAgent(step.agent_id, {
                status: "accepted",
                capabilityId: step.capability_id,
                description: step.description,
              });
            }

            addEvent({
              id,
              timestamp: ts,
              category: "phase",
              phase: "plan_proposed",
              summary: `Execution plan proposed: ${payload.capability_description}`,
              detail: payload.composition_plan,
              progress: 0.7,
              envelope,
            });
          } else {
            updateAgent(envelope.sender.id, {
              status: "offered",
              capabilityId: payload.capability_id,
              description: payload.capability_description,
              estimatedCost: payload.estimated_cost ?? undefined,
              estimatedLatency: payload.estimated_latency ?? undefined,
              outputSchema: payload.output_schema,
            });

            addEvent({
              id,
              timestamp: ts,
              category: "negotiation",
              phase: "negotiation",
              summary: `Offer from ${envelope.sender.id}: ${payload.capability_description}`,
              agentId: envelope.sender.id,
              detail: envelope.payload,
              envelope,
            });
          }
          break;
        }

        case "accept":
          setCurrentPhase("approved");
          setAwaitingApproval(false);
          addEvent({
            id,
            timestamp: ts,
            category: "phase",
            phase: "approved",
            summary:
              ((envelope.payload as Record<string, unknown>)
                .approval_note as string) ||
              "Plan approved — execution starting",
            progress: 0.72,
            envelope,
          });
          break;

        case "reject":
          addEvent({
            id,
            timestamp: ts,
            category: "warning",
            phase: "negotiation",
            summary:
              ((envelope.payload as Record<string, unknown>).reason as string) ||
              "Rejected",
            envelope,
          });
          break;

        case "execute":
          setCurrentPhase("execution");
          addEvent({
            id,
            timestamp: ts,
            category: "execution",
            phase: "execution",
            summary: "Execution in progress…",
            progress: 0.85,
            envelope,
          });
          break;

        case "complete": {
          const compPayload = envelope.payload as Record<string, unknown>;
          const execResult: ExecutionResult = {
            status:
              (compPayload.status as ExecutionResult["status"]) || "success",
            artifacts:
              (compPayload.artifacts as Record<string, unknown>[]) || [],
            metadata:
              (compPayload.metadata as Record<string, unknown>) || {},
          };
          setResult(execResult);
          setCurrentPhase("complete");

          // Build a lookup from agent_metrics so we can enrich agent cards
          const metricsByAgent = new Map<string, {
            quality_score: number;
            quality_rationale: string;
            latency_ms: number;
            retries: number;
          }>();
          const rawMetrics = (execResult.metadata.agent_metrics ?? []) as {
            agent_id: string;
            quality_score: number;
            quality_rationale: string;
            latency_ms: number;
            retries: number;
          }[];
          for (const m of rawMetrics) {
            metricsByAgent.set(m.agent_id, m);
          }

          setAgents((prev) => {
            const next = new Map(prev);
            for (const [key, agent] of next) {
              const metrics = metricsByAgent.get(key);
              if (
                agent.status === "executing" ||
                agent.status === "accepted"
              ) {
                next.set(key, {
                  ...agent,
                  status: "completed",
                  ...(metrics && {
                    qualityScore: metrics.quality_score,
                    qualityRationale: metrics.quality_rationale,
                    latencyMs: metrics.latency_ms,
                    retries: metrics.retries,
                  }),
                });
              } else if (metrics) {
                // Agent already had another status but we still have metrics
                next.set(key, {
                  ...agent,
                  qualityScore: metrics.quality_score,
                  qualityRationale: metrics.quality_rationale,
                  latencyMs: metrics.latency_ms,
                  retries: metrics.retries,
                });
              }
            }
            return next;
          });

          addEvent({
            id,
            timestamp: ts,
            category: "complete",
            phase: "complete",
            summary:
              execResult.status === "success"
                ? "Execution completed successfully"
                : `Execution finished: ${execResult.status}`,
            detail: envelope.payload,
            progress: 0.95,
            envelope,
          });
          break;
        }

        case "dissolve":
          setCurrentPhase("dissolution");
          addEvent({
            id,
            timestamp: ts,
            category: "dissolve",
            phase: "dissolution",
            summary:
              ((envelope.payload as Record<string, unknown>).reason as string) ||
              "Session dissolved",
            progress: 1.0,
            envelope,
          });
          setStatus("disconnected");
          wsRef.current?.close();
          wsRef.current = null;
          break;

        case "event": {
          const evtPayload = envelope.payload as unknown as EventPayload;
          const phase = (evtPayload.phase || undefined) as SessionPhase | undefined;

          // Only advance the phase forward — never regress to "idle" or an
          // earlier phase because of a stale / out-of-order event message.
          // "idle" is reserved for the explicit reset() action.
          if (phase && phase !== "idle") {
            setCurrentPhase(phase);
          }

          if (
            evtPayload.category === "discovery" &&
            evtPayload.detail?.agents
          ) {
            const discoveredAgents = evtPayload.detail.agents as string[];
            for (const agentId of discoveredAgents) {
              updateAgent(agentId, { status: "discovered" });
            }
          }

          if (
            evtPayload.category === "phase" &&
            evtPayload.detail?.sub_intents
          ) {
            setDecomposition(evtPayload.detail);
          }
          if (phase === "decomposition" && evtPayload.detail) {
            setDecomposition(evtPayload.detail);
          }

          if (evtPayload.category === "negotiation" && evtPayload.agent_id) {
            const summary = evtPayload.summary.toLowerCase();
            if (summary.includes("accepted")) {
              updateAgent(evtPayload.agent_id, { status: "accepted" });
            } else if (summary.includes("rejected")) {
              updateAgent(evtPayload.agent_id, { status: "rejected" });
            }
          }

          if (evtPayload.agent_id) {
            if (evtPayload.category === "execution") {
              updateAgent(evtPayload.agent_id, { status: "executing" });
            }
            if (evtPayload.category === "validation") {
              const summary = evtPayload.summary.toLowerCase();
              if (summary.includes("approved")) {
                updateAgent(evtPayload.agent_id, { status: "completed" });
              } else if (summary.includes("rejected")) {
                updateAgent(evtPayload.agent_id, { status: "rejected" });
              } else {
                updateAgent(evtPayload.agent_id, { status: "executing" });
              }
            }
          }

          addEvent({
            id,
            timestamp: ts,
            category: evtPayload.category as TimelineEvent["category"],
            phase: phase ?? "idle",
            summary: evtPayload.summary || "Progress update",
            detail: evtPayload.detail,
            agentId: evtPayload.agent_id || undefined,
            progress: evtPayload.progress ?? undefined,
            envelope,
          });
          break;
        }
      }
    },
    [addEvent, updateAgent],
  );

  const submitIntent = useCallback(
    (text: string, context?: Record<string, unknown>, assignedAgentId?: string) => {
      const sid = `${senderRef.current.id}-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
      setSessionId(sid);
      setStatus("connecting");
      setIntentText(text);
      setAssignedAgentId(assignedAgentId ?? "");
      setCurrentPhase("created");
      setProgress(0);
      setEvents([]);
      setAgents(new Map());
      setPlan(null);
      setAwaitingApproval(false);
      setResult(null);
      setDecomposition(null);

      addEvent({
        id: `user-${Date.now()}`,
        timestamp: new Date().toISOString(),
        category: "user",
        phase: "created",
        summary: text,
      });

      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        setStatus("connected");

        const envelope = makeEnvelope("intent", sid, senderRef.current, {
          intent_text: text,
          context: context ?? {},
          requested_outputs: [],
          ibac_claims_requested: [],
          ...(assignedAgentId ? { assigned_agent_id: assignedAgentId } : {}),
        });
        ws.send(JSON.stringify(envelope));

        addEvent({
          id: `system-${Date.now()}`,
          timestamp: new Date().toISOString(),
          category: "system",
          phase: "created",
          summary: "Intent submitted — waiting for coordinator…",
          progress: 0.05,
        });
      };

      ws.onmessage = (event) => {
        try {
          const envelope: AgBusEnvelope = JSON.parse(event.data as string);
          handleEnvelope(envelope);
        } catch {
          addEvent({
            id: `error-${Date.now()}`,
            timestamp: new Date().toISOString(),
            category: "error",
            phase: "error",
            summary: `Failed to parse message: ${event.data}`,
          });
        }
      };

      ws.onerror = () => {
        setStatus("error");
        setCurrentPhase("error");
        addEvent({
          id: `error-${Date.now()}`,
          timestamp: new Date().toISOString(),
          category: "error",
          phase: "error",
          summary: "WebSocket connection error — is the coordinator running?",
        });
      };

      ws.onclose = () => {
        if (status !== "error") {
          setStatus("disconnected");
        }
      };
    },
    [addEvent, handleEnvelope, status],
  );

  const sendDecision = useCallback(
    (
      action: PlanAction,
      reason = "",
      renegotiationHint?: Record<string, unknown>,
    ) => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN || !sessionId) return;

      setAwaitingApproval(false);

      if (action === "approve") {
        const envelope = makeEnvelope("accept", sessionId, senderRef.current, {
          accepted_offers: [],
          composition_plan: {},
          constraints: {},
          output_schema: {},
          approval_note: reason,
        });
        ws.send(JSON.stringify(envelope));
        addEvent({
          id: `user-decision-${Date.now()}`,
          timestamp: new Date().toISOString(),
          category: "user",
          phase: "approved",
          summary: reason ? `Approved: ${reason}` : "Plan approved ✓",
        });
      } else {
        const envelope = makeEnvelope("reject", sessionId, senderRef.current, {
          rejected_offers: [],
          reason,
          renegotiation_hint: renegotiationHint ?? {},
          renegotiate: action === "renegotiate",
        });
        ws.send(JSON.stringify(envelope));
        addEvent({
          id: `user-decision-${Date.now()}`,
          timestamp: new Date().toISOString(),
          category: "user",
          phase: "negotiation",
          summary:
            action === "renegotiate"
              ? `Renegotiation requested: ${reason}`
              : `Plan rejected: ${reason}`,
        });

        if (action === "renegotiate") {
          setCurrentPhase("discovery");
          setPlan(null);
        }
      }
    },
    [sessionId, addEvent],
  );

  const disconnect = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
    setStatus("disconnected");
  }, []);

  const reset = useCallback(() => {
    setEvents([]);
    setSessionId(null);
    setCurrentPhase("idle");
    setProgress(0);
    setAgents(new Map());
    setPlan(null);
    setAwaitingApproval(false);
    setResult(null);
    setIntentText("");
    setDecomposition(null);
    setAssignedAgentId("");
    disconnect();
  }, [disconnect]);

  return {
    status,
    sessionId,
    currentPhase,
    progress,
    events,
    agents,
    plan,
    awaitingApproval,
    result,
    intentText,
    decomposition,
    assignedAgentId,
    submitIntent,
    sendDecision,
    disconnect,
    reset,
  } as const;
}
