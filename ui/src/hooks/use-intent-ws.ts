"use client";

import { useCallback, useRef, useState } from "react";
import type {
  AgBusEnvelope,
  MessageType,
  OfferPayload,
  SenderInfo,
} from "@/lib/protocol";
import { makeEnvelope } from "@/lib/protocol";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ConnectionStatus = "disconnected" | "connecting" | "connected" | "error";

export type PlanAction = "approve" | "reject" | "renegotiate";

/** A single entry in the chat timeline. */
export interface ChatMessage {
  id: string;
  timestamp: string;
  role: "user" | "system" | "offer" | "plan" | "accept" | "reject" | "execute" | "complete" | "dissolve" | "error";
  content: string;
  envelope?: AgBusEnvelope;
  /** For plan messages – waiting for user decision */
  awaitingDecision?: boolean;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8765";

export function useIntentWs() {
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const senderRef = useRef<SenderInfo>({
    kind: "requester",
    id: `ui-${Date.now().toString(36)}`,
    oidc_subject: "",
  });

  // -----------------------------------------------------------------------
  // helpers
  // -----------------------------------------------------------------------

  const addMessage = useCallback((msg: ChatMessage) => {
    setMessages((prev) => [...prev, msg]);
  }, []);

  const updateLastPlan = useCallback((decided: boolean) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.role === "plan" && m.awaitingDecision ? { ...m, awaitingDecision: !decided } : m,
      ),
    );
  }, []);

  // -----------------------------------------------------------------------
  // Message handler
  // -----------------------------------------------------------------------

  const handleEnvelope = useCallback(
    (envelope: AgBusEnvelope) => {
      const ts = envelope.timestamp;
      const id = envelope.message_id;

      // Adopt the coordinator's authoritative session_id so that
      // subsequent messages (accept / reject) reference the correct session.
      if (envelope.session_id) {
        setSessionId(envelope.session_id);
      }

      switch (envelope.message_type as MessageType) {
        case "offer": {
          const payload = envelope.payload as unknown as OfferPayload;
          if (payload.capability_id === "__composed_plan__") {
            addMessage({
              id,
              timestamp: ts,
              role: "plan",
              content: payload.capability_description || "Execution plan proposed",
              envelope,
              awaitingDecision: true,
            });
          } else {
            addMessage({
              id,
              timestamp: ts,
              role: "offer",
              content:
                payload.capability_description ||
                `Offer from agent: ${payload.capability_id}`,
              envelope,
            });
          }
          break;
        }

        case "accept":
          addMessage({
            id,
            timestamp: ts,
            role: "accept",
            content:
              (envelope.payload as Record<string, unknown>).approval_note as string ||
              "Plan accepted – execution starting…",
            envelope,
          });
          break;

        case "reject":
          addMessage({
            id,
            timestamp: ts,
            role: "reject",
            content:
              (envelope.payload as Record<string, unknown>).reason as string ||
              "Rejected",
            envelope,
          });
          break;

        case "execute":
          addMessage({
            id,
            timestamp: ts,
            role: "execute",
            content: "Execution in progress…",
            envelope,
          });
          break;

        case "complete": {
          const status = (envelope.payload as Record<string, unknown>).status as string;
          addMessage({
            id,
            timestamp: ts,
            role: "complete",
            content:
              status === "success"
                ? "Execution completed successfully"
                : `Execution finished with status: ${status}`,
            envelope,
          });
          break;
        }

        case "dissolve":
          addMessage({
            id,
            timestamp: ts,
            role: "dissolve",
            content:
              (envelope.payload as Record<string, unknown>).reason as string ||
              "Session dissolved",
            envelope,
          });
          setStatus("disconnected");
          wsRef.current?.close();
          wsRef.current = null;
          break;
      }
    },
    [addMessage],
  );

  // -----------------------------------------------------------------------
  // Submit intent
  // -----------------------------------------------------------------------

  const submitIntent = useCallback(
    (intentText: string, context?: Record<string, unknown>) => {
      // Generate session id (mirrors Python IntentClient._generate_session_id)
      const sid = `${senderRef.current.id}-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
      setSessionId(sid);
      setStatus("connecting");

      // Reset chat for new session (keep old messages for history, add separator)
      addMessage({
        id: `user-${Date.now()}`,
        timestamp: new Date().toISOString(),
        role: "user",
        content: intentText,
      });

      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        setStatus("connected");

        const envelope = makeEnvelope("intent", sid, senderRef.current, {
          intent_text: intentText,
          context: context ?? {},
          requested_outputs: [],
          ibac_claims_requested: [],
        });
        ws.send(JSON.stringify(envelope));

        addMessage({
          id: `system-${Date.now()}`,
          timestamp: new Date().toISOString(),
          role: "system",
          content: "Intent submitted – waiting for coordinator…",
        });
      };

      ws.onmessage = (event) => {
        try {
          const envelope: AgBusEnvelope = JSON.parse(event.data as string);
          handleEnvelope(envelope);
        } catch {
          addMessage({
            id: `error-${Date.now()}`,
            timestamp: new Date().toISOString(),
            role: "error",
            content: `Failed to parse message: ${event.data}`,
          });
        }
      };

      ws.onerror = () => {
        setStatus("error");
        addMessage({
          id: `error-${Date.now()}`,
          timestamp: new Date().toISOString(),
          role: "error",
          content: "WebSocket connection error – is the coordinator running?",
        });
      };

      ws.onclose = () => {
        if (status !== "error") {
          setStatus("disconnected");
        }
      };
    },
    [addMessage, handleEnvelope, status],
  );

  // -----------------------------------------------------------------------
  // Plan decisions
  // -----------------------------------------------------------------------

  const sendDecision = useCallback(
    (action: PlanAction, reason = "", renegotiationHint?: Record<string, unknown>) => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN || !sessionId) return;

      updateLastPlan(true);

      if (action === "approve") {
        const envelope = makeEnvelope("accept", sessionId, senderRef.current, {
          accepted_offers: [],
          composition_plan: {},
          constraints: {},
          output_schema: {},
          approval_note: reason,
        });
        ws.send(JSON.stringify(envelope));
        addMessage({
          id: `user-decision-${Date.now()}`,
          timestamp: new Date().toISOString(),
          role: "user",
          content: reason ? `Approved: ${reason}` : "Plan approved ✓",
        });
      } else {
        const envelope = makeEnvelope("reject", sessionId, senderRef.current, {
          rejected_offers: [],
          reason,
          renegotiation_hint: renegotiationHint ?? {},
          renegotiate: action === "renegotiate",
        });
        ws.send(JSON.stringify(envelope));
        addMessage({
          id: `user-decision-${Date.now()}`,
          timestamp: new Date().toISOString(),
          role: "user",
          content:
            action === "renegotiate"
              ? `Renegotiation requested: ${reason}`
              : `Plan rejected: ${reason}`,
        });
      }
    },
    [sessionId, addMessage, updateLastPlan],
  );

  // -----------------------------------------------------------------------
  // Cleanup
  // -----------------------------------------------------------------------

  const disconnect = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
    setStatus("disconnected");
  }, []);

  const clearChat = useCallback(() => {
    setMessages([]);
    setSessionId(null);
    disconnect();
  }, [disconnect]);

  return {
    status,
    messages,
    sessionId,
    submitIntent,
    sendDecision,
    disconnect,
    clearChat,
  } as const;
}
