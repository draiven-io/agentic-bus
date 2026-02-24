"use client";

import { useRef, useEffect, useState, useMemo, type KeyboardEvent } from "react";
import {
  Send,
  Loader2,
  CheckCircle2,
  XCircle,
  Bot,
  Zap,
  ThumbsUp,
  ThumbsDown,
  RefreshCw,
  RotateCcw,
  WifiOff,
  Wifi,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Play,
  Activity,
  Shield,
  Search,
  GitBranch,
  Circle,
  Sparkles,
  ArrowRight,
  Clock,
  DollarSign,
  Terminal,
  CheckCheck,
  XOctagon,
  Network,
  Star,
  MessageSquareText,
  Gauge,
  RotateCw,
  FileText,
  Quote,
} from "lucide-react";
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  Position,
  MarkerType,
  Handle,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { motion, AnimatePresence } from "framer-motion";

import { AppHeader } from "@/components/app-header";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from "@/components/ui/resizable";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { AgentSelect } from "@/components/agent-select";

import {
  useIntentWs,
  type ConnectionStatus,
  type SessionPhase,
  type TimelineEvent,
  type FlowAgent,
  type ExecutionPlan,
} from "@/hooks/use-intent-ws";

// ---------------------------------------------------------------------------
// Phase pipeline config
// ---------------------------------------------------------------------------

const PHASES: {
  key: SessionPhase;
  label: string;
  icon: typeof Activity;
  color: string;
}[] = [
  { key: "created", label: "Intent", icon: Sparkles, color: "text-blue-400" },
  { key: "intent_admission", label: "IBAC", icon: Shield, color: "text-purple-400" },
  { key: "decomposition", label: "Decompose", icon: GitBranch, color: "text-cyan-400" },
  { key: "discovery", label: "Discovery", icon: Search, color: "text-teal-400" },
  { key: "negotiation", label: "Negotiate", icon: Activity, color: "text-amber-400" },
  { key: "plan_proposed", label: "Plan", icon: Network, color: "text-orange-400" },
  { key: "execution", label: "Execute", icon: Play, color: "text-violet-400" },
  { key: "validation", label: "Validate", icon: Shield, color: "text-cyan-400" },
  { key: "complete", label: "Complete", icon: CheckCircle2, color: "text-emerald-400" },
];

function phaseIndex(phase: SessionPhase): number {
  const idx = PHASES.findIndex((p) => p.key === phase);
  // Map derived phases to their parent
  if (phase === "intent_received") return 0;
  if (phase === "approved") return 7;
  if (phase === "dissolution") return 8;
  return idx >= 0 ? idx : -1;
}

// ---------------------------------------------------------------------------
// Status indicator
// ---------------------------------------------------------------------------

function StatusDot({ status }: { status: ConnectionStatus }) {
  const cfg: Record<
    ConnectionStatus,
    { color: string; label: string; Icon: typeof Wifi }
  > = {
    disconnected: { color: "bg-muted-foreground", label: "Disconnected", Icon: WifiOff },
    connecting: { color: "bg-yellow-500 animate-pulse", label: "Connecting…", Icon: Wifi },
    connected: { color: "bg-green-500", label: "Connected", Icon: Wifi },
    error: { color: "bg-red-500", label: "Error", Icon: AlertCircle },
  };
  const { color, label, Icon } = cfg[status];
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <Icon className="size-3.5" />
      <span className={`inline-block size-2 rounded-full ${color}`} />
      {label}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Phase pipeline stepper
// ---------------------------------------------------------------------------

function PhasePipeline({ currentPhase, progress }: { currentPhase: SessionPhase; progress: number }) {
  const activeIdx = phaseIndex(currentPhase);

  return (
    <div className="flex items-center gap-1 px-4 py-3">
      {PHASES.map((phase, idx) => {
        const isActive = idx === activeIdx;
        const isDone = idx < activeIdx;
        const isFuture = idx > activeIdx;
        const Icon = phase.icon;

        return (
          <div key={phase.key} className="flex items-center gap-1">
            <div
              className={`
                flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium transition-all duration-500
                ${isActive ? `${phase.color} bg-white/5 ring-1 ring-white/10` : ""}
                ${isDone ? "text-emerald-400/70" : ""}
                ${isFuture ? "text-muted-foreground/40" : ""}
              `}
            >
              {isDone ? (
                <CheckCircle2 className="size-3" />
              ) : isActive ? (
                <Icon className="size-3 animate-pulse" />
              ) : (
                <Circle className="size-3" />
              )}
              <span className="hidden lg:inline">{phase.label}</span>
            </div>
            {idx < PHASES.length - 1 && (
              <ArrowRight
                className={`size-3 ${
                  idx < activeIdx ? "text-emerald-400/50" : "text-muted-foreground/20"
                }`}
              />
            )}
          </div>
        );
      })}

      {/* Global progress */}
      <div className="ml-auto flex items-center gap-2">
        <div className="h-1.5 w-24 rounded-full bg-muted overflow-hidden">
          <motion.div
            className="h-full rounded-full bg-gradient-to-r from-blue-500 via-violet-500 to-emerald-500"
            initial={{ width: 0 }}
            animate={{ width: `${Math.round(progress * 100)}%` }}
            transition={{ duration: 0.5, ease: "easeOut" }}
          />
        </div>
        <span className="text-[10px] text-muted-foreground tabular-nums font-mono">
          {Math.round(progress * 100)}%
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Execution graph (React Flow)
// ---------------------------------------------------------------------------

function CoordinatorNode({ data }: { data: { label: string } }) {
  return (
    <div className="rounded-lg bg-gradient-to-br from-violet-600/20 to-violet-900/30 border border-violet-500/30 px-4 py-2.5 text-center shadow-lg shadow-violet-500/5">
      <Handle type="source" position={Position.Bottom} className="!bg-violet-400 !size-2" />
      <div className="flex items-center gap-2">
        <Zap className="size-4 text-violet-400" />
        <span className="text-xs font-semibold text-violet-200">{data.label}</span>
      </div>
    </div>
  );
}

function AgentNode({
  data,
}: {
  data: {
    label: string;
    agentId: string;
    description: string;
    status: FlowAgent["status"];
    estimatedCost?: number;
    estimatedLatency?: number;
    stepIndex: number;
  };
}) {
  const statusStyles: Record<string, { border: string; bg: string; glow: string; icon: typeof Circle }> = {
    discovered: { border: "border-zinc-500/30", bg: "from-zinc-800/50 to-zinc-900/50", glow: "", icon: Circle },
    offered: { border: "border-blue-500/30", bg: "from-blue-900/30 to-blue-950/40", glow: "", icon: Activity },
    accepted: { border: "border-amber-500/40", bg: "from-amber-900/20 to-amber-950/30", glow: "shadow-amber-500/5", icon: CheckCircle2 },
    executing: { border: "border-violet-500/50 animate-pulse", bg: "from-violet-900/30 to-violet-950/40", glow: "shadow-lg shadow-violet-500/10", icon: Play },
    completed: { border: "border-emerald-500/40", bg: "from-emerald-900/20 to-emerald-950/30", glow: "shadow-emerald-500/5", icon: CheckCheck },
    rejected: { border: "border-red-500/30", bg: "from-red-900/20 to-red-950/30", glow: "", icon: XOctagon },
    error: { border: "border-red-500/40", bg: "from-red-900/30 to-red-950/40", glow: "", icon: AlertCircle },
  };

  const style = statusStyles[data.status] || statusStyles.discovered;
  const StatusIcon = style.icon;

  return (
    <div
      className={`rounded-xl bg-gradient-to-br ${style.bg} border ${style.border} px-4 py-3 min-w-[180px] ${style.glow} transition-all duration-500`}
    >
      <Handle type="target" position={Position.Top} className="!bg-zinc-400 !size-2" />
      <Handle type="source" position={Position.Bottom} className="!bg-zinc-400 !size-2" />

      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Bot className="size-4 text-zinc-300" />
          <span className="text-[11px] font-bold text-zinc-200 truncate max-w-[120px]">
            {data.agentId}
          </span>
        </div>
        <StatusIcon className="size-3.5 shrink-0" />
      </div>

      {data.description && (
        <p className="mt-1.5 text-[10px] text-zinc-400 leading-relaxed line-clamp-2">
          {data.description}
        </p>
      )}

      <div className="mt-2 flex items-center gap-2 text-[9px] text-zinc-500">
        {data.estimatedCost != null && (
          <span className="flex items-center gap-0.5">
            <DollarSign className="size-2.5" />
            {data.estimatedCost}
          </span>
        )}
        {data.estimatedLatency != null && (
          <span className="flex items-center gap-0.5">
            <Clock className="size-2.5" />
            {data.estimatedLatency}s
          </span>
        )}
        <Badge
          variant="outline"
          className="ml-auto text-[8px] px-1 py-0 h-3.5 border-zinc-700"
        >
          Step {data.stepIndex + 1}
        </Badge>
      </div>
    </div>
  );
}

function EndNode({ data }: { data: { label: string; success?: boolean } }) {
  return (
    <div
      className={`rounded-lg px-4 py-2.5 text-center border shadow-lg ${
        data.success
          ? "bg-gradient-to-br from-emerald-600/20 to-emerald-900/30 border-emerald-500/30 shadow-emerald-500/5"
          : "bg-gradient-to-br from-zinc-700/20 to-zinc-900/30 border-zinc-600/30"
      }`}
    >
      <Handle type="target" position={Position.Top} className="!bg-zinc-400 !size-2" />
      <div className="flex items-center gap-2">
        {data.success ? (
          <CheckCircle2 className="size-4 text-emerald-400" />
        ) : (
          <Circle className="size-4 text-zinc-500" />
        )}
        <span
          className={`text-xs font-semibold ${
            data.success ? "text-emerald-200" : "text-zinc-400"
          }`}
        >
          {data.label}
        </span>
      </div>
    </div>
  );
}

function ValidatorNode({
  data,
}: {
  data: {
    label: string;
    agentId: string;
    status: "idle" | "validating" | "approved" | "rejected" | "renegotiating";
    round?: number;
    maxRounds?: number;
  };
}) {
  const statusStyles: Record<string, { border: string; bg: string; glow: string; text: string }> = {
    idle: { border: "border-cyan-500/20", bg: "from-cyan-900/10 to-cyan-950/20", glow: "", text: "text-cyan-400/60" },
    validating: { border: "border-cyan-500/50 animate-pulse", bg: "from-cyan-900/30 to-cyan-950/40", glow: "shadow-lg shadow-cyan-500/10", text: "text-cyan-300" },
    approved: { border: "border-emerald-500/40", bg: "from-emerald-900/20 to-emerald-950/30", glow: "shadow-emerald-500/5", text: "text-emerald-300" },
    rejected: { border: "border-red-500/40", bg: "from-red-900/20 to-red-950/30", glow: "shadow-red-500/5", text: "text-red-300" },
    renegotiating: { border: "border-amber-500/50 animate-pulse", bg: "from-amber-900/20 to-amber-950/30", glow: "shadow-lg shadow-amber-500/10", text: "text-amber-300" },
  };

  const style = statusStyles[data.status] || statusStyles.idle;

  const statusLabel: Record<string, string> = {
    idle: "Awaiting output…",
    validating: "Validating…",
    approved: "Approved ✓",
    rejected: "Rejected ✗",
    renegotiating: "Renegotiating…",
  };

  return (
    <div
      className={`rounded-xl bg-gradient-to-br ${style.bg} border ${style.border} px-4 py-3 min-w-[180px] ${style.glow} transition-all duration-500`}
    >
      <Handle type="target" position={Position.Top} className="!bg-cyan-400 !size-2" />
      <Handle type="source" position={Position.Bottom} className="!bg-cyan-400 !size-2" />
      <Handle type="source" position={Position.Left} id="renegotiate" className="!bg-amber-400 !size-2" />

      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Shield className="size-4 text-cyan-400" />
          <span className={`text-[11px] font-bold ${style.text} truncate max-w-[120px]`}>
            {data.agentId}
          </span>
        </div>
        <Badge
          variant="outline"
          className="text-[8px] px-1 py-0 h-3.5 border-cyan-700/50 text-cyan-400"
        >
          Validator
        </Badge>
      </div>

      <p className="mt-1.5 text-[10px] text-zinc-400 leading-relaxed">
        {statusLabel[data.status] || "Validation"}
      </p>

      {data.round != null && data.round > 0 && (
        <div className="mt-1.5 flex items-center gap-1.5 text-[9px] text-zinc-500">
          <RotateCw className="size-2.5" />
          Round {data.round}/{data.maxRounds ?? 3}
        </div>
      )}
    </div>
  );
}

const nodeTypes = {
  coordinator: CoordinatorNode,
  agent: AgentNode,
  end: EndNode,
  validator: ValidatorNode,
};

function ExecutionGraph({
  plan,
  agents,
  currentPhase,
  result,
  assignedAgentId,
}: {
  plan: ExecutionPlan | null;
  agents: Map<string, FlowAgent>;
  currentPhase: SessionPhase;
  result: ReturnType<typeof useIntentWs>["result"];
  assignedAgentId: string;
}) {
  const { nodes, edges } = useMemo(() => {
    const n: Node[] = [];
    const e: Edge[] = [];

    if (!plan || plan.steps.length === 0) {
      // Show placeholder
      n.push({
        id: "placeholder",
        type: "coordinator",
        position: { x: 100, y: 80 },
        data: { label: "Awaiting execution plan…" },
      });
      return { nodes: n, edges: e };
    }

    const hasValidator = !!assignedAgentId;
    const centerX = 200;
    const startY = 30;
    const nodeSpacing = 130;

    // Coordinator node
    n.push({
      id: "coordinator",
      type: "coordinator",
      position: { x: centerX - 60, y: startY },
      data: { label: "Coordinator" },
    });

    // Agent nodes — use step index for unique IDs since the same agent
    // can appear in multiple steps of the composition plan.
    plan.steps.forEach((step, i) => {
      const agentData = agents.get(step.agentId);
      const nodeId = `step-${i}`;
      n.push({
        id: nodeId,
        type: "agent",
        position: { x: centerX - 90, y: startY + 80 + i * nodeSpacing },
        data: {
          label: step.agentId,
          agentId: step.agentId,
          description: step.description || agentData?.description || "",
          status: agentData?.status || "accepted",
          estimatedCost: agentData?.estimatedCost,
          estimatedLatency: agentData?.estimatedLatency,
          stepIndex: i,
        },
      });

      // Edge from previous
      const sourceId = i === 0 ? "coordinator" : `step-${i - 1}`;
      e.push({
        id: `e-${sourceId}-${nodeId}`,
        source: sourceId,
        target: nodeId,
        animated: currentPhase === "execution",
        style: {
          stroke:
            currentPhase === "execution" ? "#8b5cf6" :
            currentPhase === "complete" ? "#10b981" : "#52525b",
          strokeWidth: 2,
        },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#52525b" },
      });
    });

    const lastStepIdx = plan.steps.length - 1;

    if (hasValidator) {
      // ── Validator node between last step and end ──
      const validatorY = startY + 80 + plan.steps.length * nodeSpacing;
      const validatorX = centerX - 90;

      // Determine the validator's visual status from the current phase and
      // any agent data we might have for it.
      const validatorAgentData = agents.get(assignedAgentId);
      let validatorStatus: "idle" | "validating" | "approved" | "rejected" | "renegotiating" = "idle";
      if (currentPhase === "validation") {
        if (validatorAgentData?.status === "completed") {
          validatorStatus = "approved";
        } else if (validatorAgentData?.status === "rejected") {
          validatorStatus = "rejected";
        } else {
          validatorStatus = "validating";
        }
      } else if (currentPhase === "complete" || currentPhase === "dissolution") {
        if (validatorAgentData?.status === "rejected") {
          validatorStatus = "rejected";
        } else {
          validatorStatus = "approved";
        }
      } else if (
        currentPhase === "discovery" ||
        currentPhase === "negotiation" ||
        currentPhase === "plan_proposed"
      ) {
        // If we're back in discovery/negotiation after execution, it's a renegotiation
        if (validatorAgentData?.status === "rejected") {
          validatorStatus = "renegotiating";
        }
      }

      n.push({
        id: "validator",
        type: "validator",
        position: { x: validatorX, y: validatorY },
        data: {
          label: assignedAgentId,
          agentId: assignedAgentId,
          status: validatorStatus,
          round: 0,
          maxRounds: 3,
        },
      });

      // Edge: last step → validator
      if (lastStepIdx >= 0) {
        const lastNodeId = `step-${lastStepIdx}`;
        e.push({
          id: `e-${lastNodeId}-validator`,
          source: lastNodeId,
          target: "validator",
          animated: currentPhase === "execution" || currentPhase === "validation",
          style: {
            stroke:
              currentPhase === "validation" ? "#06b6d4" :
              currentPhase === "execution" ? "#8b5cf6" : "#52525b",
            strokeWidth: 2,
          },
          markerEnd: { type: MarkerType.ArrowClosed, color: "#06b6d4" },
        });
      }

      // Edge: validator → end (success path)
      const endY = validatorY + nodeSpacing;
      const isComplete = currentPhase === "complete" || currentPhase === "dissolution";

      n.push({
        id: "end",
        type: "end",
        position: { x: centerX - 40, y: endY },
        data: {
          label: isComplete
            ? result?.status === "success"
              ? "Success"
              : `Done (${result?.status || "?"})`
            : "End",
          success: isComplete && result?.status === "success",
        },
      });

      e.push({
        id: "e-validator-end",
        source: "validator",
        target: "end",
        animated: currentPhase === "validation",
        style: {
          stroke: isComplete ? "#10b981" : "#52525b",
          strokeWidth: 2,
        },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#52525b" },
        label: "approved",
        labelStyle: { fill: "#71717a", fontSize: 9 },
        labelBgStyle: { fill: "#18181b", fillOpacity: 0.8 },
        labelBgPadding: [4, 2] as [number, number],
      });

      // Edge: validator → coordinator (renegotiation loop — curved)
      e.push({
        id: "e-validator-coordinator-reneg",
        source: "validator",
        sourceHandle: "renegotiate",
        target: "coordinator",
        type: "smoothstep",
        animated: validatorStatus === "renegotiating",
        style: {
          stroke: "#f59e0b",
          strokeWidth: 2,
          strokeDasharray: validatorStatus === "renegotiating" ? undefined : "6 3",
          opacity: validatorStatus === "renegotiating" ? 1 : 0.4,
        },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#f59e0b" },
        label: "renegotiate",
        labelStyle: { fill: "#f59e0b", fontSize: 9 },
        labelBgStyle: { fill: "#18181b", fillOpacity: 0.8 },
        labelBgPadding: [4, 2] as [number, number],
      });
    } else {
      // No validator — original flow: last step → end
      const endY = startY + 80 + plan.steps.length * nodeSpacing;
      const isComplete = currentPhase === "complete" || currentPhase === "dissolution";

      n.push({
        id: "end",
        type: "end",
        position: { x: centerX - 40, y: endY },
        data: {
          label: isComplete
            ? result?.status === "success"
              ? "Success"
              : `Done (${result?.status || "?"})`
            : "End",
          success: isComplete && result?.status === "success",
        },
      });

      if (lastStepIdx >= 0) {
        const lastNodeId = `step-${lastStepIdx}`;
        e.push({
          id: `e-${lastNodeId}-end`,
          source: lastNodeId,
          target: "end",
          animated: currentPhase === "execution",
          style: {
            stroke: isComplete ? "#10b981" : "#52525b",
            strokeWidth: 2,
          },
          markerEnd: { type: MarkerType.ArrowClosed, color: "#52525b" },
        });
      }
    }

    return { nodes: n, edges: e };
  }, [plan, agents, currentPhase, result, assignedAgentId]);

  return (
    <div className="h-full w-full [&_.react-flow__attribution]:hidden">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        zoomOnScroll={false}
        panOnScroll
        minZoom={0.5}
        maxZoom={1.5}
      >
        <Background gap={20} size={1} color="rgba(255,255,255,0.03)" />
        <Controls
          showInteractive={false}
          className="!bg-zinc-900 !border-zinc-700 !shadow-lg [&>button]:!bg-zinc-800 [&>button]:!border-zinc-700 [&>button]:!text-zinc-300 [&>button:hover]:!bg-zinc-700"
        />
      </ReactFlow>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Event timeline
// ---------------------------------------------------------------------------

const categoryConfig: Record<
  string,
  { icon: typeof Activity; color: string; bgColor: string }
> = {
  user: { icon: Send, color: "text-blue-400", bgColor: "bg-blue-500/10" },
  phase: { icon: Zap, color: "text-blue-400", bgColor: "bg-blue-500/10" },
  ibac: { icon: Shield, color: "text-purple-400", bgColor: "bg-purple-500/10" },
  discovery: { icon: Search, color: "text-teal-400", bgColor: "bg-teal-500/10" },
  negotiation: { icon: Activity, color: "text-amber-400", bgColor: "bg-amber-500/10" },
  execution: { icon: Play, color: "text-violet-400", bgColor: "bg-violet-500/10" },
  agent: { icon: Bot, color: "text-emerald-400", bgColor: "bg-emerald-500/10" },
  warning: { icon: AlertCircle, color: "text-orange-400", bgColor: "bg-orange-500/10" },
  error: { icon: XCircle, color: "text-red-400", bgColor: "bg-red-500/10" },
  system: { icon: Terminal, color: "text-zinc-400", bgColor: "bg-zinc-500/10" },
  complete: { icon: CheckCircle2, color: "text-emerald-400", bgColor: "bg-emerald-500/10" },
  validation: { icon: Shield, color: "text-cyan-400", bgColor: "bg-cyan-500/10" },
  dissolve: { icon: Circle, color: "text-zinc-400", bgColor: "bg-zinc-500/10" },
};

function TimelineItem({ event, isLast }: { event: TimelineEvent; isLast: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const config = categoryConfig[event.category] || categoryConfig.system;
  const Icon = config.icon;
  const hasDetail = event.detail && Object.keys(event.detail).length > 0;

  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.3 }}
      className="relative flex gap-3"
    >
      {/* Timeline line */}
      <div className="flex flex-col items-center">
        <div
          className={`flex size-7 shrink-0 items-center justify-center rounded-full ${config.bgColor}`}
        >
          <Icon className={`size-3.5 ${config.color}`} />
        </div>
        {!isLast && <div className="w-px flex-1 bg-border/50 mt-1" />}
      </div>

      {/* Content */}
      <div className={`pb-4 min-w-0 flex-1 ${isLast ? "" : ""}`}>
        <div className="flex items-center gap-2">
          <Badge
            variant="outline"
            className={`text-[9px] px-1.5 py-0 h-4 ${config.color} border-current/20`}
          >
            {event.category}
          </Badge>
          {event.agentId && (
            <Badge variant="secondary" className="text-[9px] px-1.5 py-0 h-4">
              {event.agentId}
            </Badge>
          )}
          <span className="ml-auto text-[9px] text-muted-foreground font-mono">
            {new Date(event.timestamp).toLocaleTimeString()}
          </span>
        </div>
        <p className="mt-1 text-[12px] text-zinc-300 leading-relaxed">
          {event.summary}
        </p>

        {hasDetail && (
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className="mt-1 flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
          >
            {expanded ? (
              <ChevronUp className="size-3" />
            ) : (
              <ChevronDown className="size-3" />
            )}
            {expanded ? "Hide details" : "Show details"}
          </button>
        )}
        <AnimatePresence>
          {expanded && hasDetail && (
            <motion.pre
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="mt-1.5 max-h-48 overflow-auto rounded-md bg-zinc-900/80 border border-zinc-800 p-2 text-[10px] leading-relaxed text-zinc-400 font-mono"
            >
              {JSON.stringify(event.detail, null, 2)}
            </motion.pre>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

function EventTimeline({ events }: { events: TimelineEvent[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  if (events.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 p-8 text-center text-muted-foreground">
        <Activity className="size-8 opacity-20" />
        <p className="text-xs">Events will appear here as the negotiation progresses</p>
      </div>
    );
  }

  return (
    <div className="absolute inset-0 overflow-y-auto">
      <div className="space-y-0 p-4">
        {events.map((event, i) => (
          <TimelineItem key={event.id} event={event} isLast={i === events.length - 1} />
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Agent cards panel
// ---------------------------------------------------------------------------

function AgentCards({ agents }: { agents: Map<string, FlowAgent> }) {
  const agentList = Array.from(agents.values());

  if (agentList.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 p-8 text-center text-muted-foreground">
        <Bot className="size-8 opacity-20" />
        <p className="text-xs">Discovered agents will appear here</p>
      </div>
    );
  }

  return (
    <div className="absolute inset-0 overflow-y-auto">
      <div className="space-y-2 p-4">
        {agentList.map((agent) => {
          const statusStyles: Record<string, string> = {
            discovered: "border-zinc-600/30 text-zinc-400",
            offered: "border-blue-500/30 text-blue-400",
            accepted: "border-amber-500/30 text-amber-400",
            rejected: "border-red-500/30 text-red-400",
            executing: "border-violet-500/30 text-violet-400",
            completed: "border-emerald-500/30 text-emerald-400",
            error: "border-red-500/40 text-red-400",
          };
          const statusIcons: Record<string, typeof Circle> = {
            discovered: Circle,
            offered: Activity,
            accepted: CheckCircle2,
            rejected: XOctagon,
            executing: Play,
            completed: CheckCheck,
            error: AlertCircle,
          };
          const StatusIcon = statusIcons[agent.status] || Circle;

          const hasMetrics = agent.qualityScore != null;
          const scoreColor =
            (agent.qualityScore ?? 0) >= 8
              ? "text-emerald-400"
              : (agent.qualityScore ?? 0) >= 5
                ? "text-amber-400"
                : "text-red-400";
          const scoreBg =
            (agent.qualityScore ?? 0) >= 8
              ? "bg-emerald-500/10 border-emerald-500/20"
              : (agent.qualityScore ?? 0) >= 5
                ? "bg-amber-500/10 border-amber-500/20"
                : "bg-red-500/10 border-red-500/20";

          return (
            <motion.div
              key={agent.agentId}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3 }}
            >
              <Card className="border-zinc-800 bg-zinc-900/50">
                <CardContent className="p-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Bot className="size-4 text-zinc-400" />
                      <span className="text-xs font-semibold text-zinc-200 truncate max-w-[130px]">
                        {agent.agentId}
                      </span>
                    </div>
                    <Badge
                      variant="outline"
                      className={`text-[9px] px-1.5 py-0 ${statusStyles[agent.status] || ""}`}
                    >
                      <StatusIcon className="size-2.5 mr-1" />
                      {agent.status}
                    </Badge>
                  </div>
                  {agent.capabilityId && (
                    <p className="mt-1.5 text-[10px] text-zinc-500 font-mono">
                      {agent.capabilityId}
                    </p>
                  )}
                  {agent.description && (
                    <p className="mt-1 text-[10px] text-zinc-400 line-clamp-2">
                      {agent.description}
                    </p>
                  )}

                  {/* Quality metrics (populated after execution completes) */}
                  {hasMetrics && (
                    <div className="mt-2.5 rounded-md border border-zinc-800 bg-zinc-950/50 p-2">
                      <div className="flex items-center gap-2">
                        <div
                          className={`flex size-7 shrink-0 items-center justify-center rounded-full border ${scoreBg}`}
                        >
                          <span className={`text-[11px] font-bold tabular-nums ${scoreColor}`}>
                            {agent.qualityScore}
                          </span>
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 text-[9px] text-zinc-500">
                            <span className="flex items-center gap-0.5">
                              <Clock className="size-2.5" />
                              {(agent.latencyMs ?? 0).toFixed(0)}ms
                            </span>
                            <span className="flex items-center gap-0.5">
                              <Star className="size-2.5" />
                              {agent.qualityScore}/10
                            </span>
                            {(agent.retries ?? 0) > 0 && (
                              <span className="flex items-center gap-0.5 text-amber-500">
                                <RotateCw className="size-2.5" />
                                {agent.retries}
                              </span>
                            )}
                          </div>
                          {agent.qualityRationale && (
                            <p className="mt-1 text-[9px] text-zinc-500 leading-relaxed italic line-clamp-2">
                              {agent.qualityRationale}
                            </p>
                          )}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Pre-execution estimates (shown when no metrics yet) */}
                  {!hasMetrics && (agent.estimatedCost != null || agent.estimatedLatency != null) && (
                    <div className="mt-2 flex gap-3 text-[9px] text-zinc-500">
                      {agent.estimatedCost != null && (
                        <span className="flex items-center gap-0.5">
                          <DollarSign className="size-2.5" /> {agent.estimatedCost}
                        </span>
                      )}
                      {agent.estimatedLatency != null && (
                        <span className="flex items-center gap-0.5">
                          <Clock className="size-2.5" /> {agent.estimatedLatency}s
                        </span>
                      )}
                    </div>
                  )}
                </CardContent>
              </Card>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Result panel
// ---------------------------------------------------------------------------

interface AgentMetric {
  agent_id: string;
  latency_ms: number;
  quality_score: number;
  quality_rationale: string;
  retries: number;
}

function ScoreRing({ score }: { score: number }) {
  // Score is 0-10. Map to colour.
  const pct = Math.max(0, Math.min(score, 10)) / 10;
  const color =
    pct >= 0.8
      ? "text-emerald-400"
      : pct >= 0.5
        ? "text-amber-400"
        : "text-red-400";
  const bgColor =
    pct >= 0.8
      ? "bg-emerald-500/10 border-emerald-500/20"
      : pct >= 0.5
        ? "bg-amber-500/10 border-amber-500/20"
        : "bg-red-500/10 border-red-500/20";

  return (
    <div
      className={`flex size-10 shrink-0 items-center justify-center rounded-full border ${bgColor}`}
    >
      <span className={`text-sm font-bold tabular-nums ${color}`}>{score}</span>
    </div>
  );
}

function AgentMetricCard({ metric }: { metric: AgentMetric }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3"
    >
      <div className="flex items-start gap-3">
        <ScoreRing score={metric.quality_score} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Bot className="size-3.5 text-zinc-400" />
            <span className="text-[11px] font-semibold text-zinc-200 truncate">
              {metric.agent_id}
            </span>
          </div>

          {/* Stats row */}
          <div className="mt-1.5 flex items-center gap-3 text-[10px] text-zinc-500">
            <span className="flex items-center gap-1">
              <Clock className="size-2.5" />
              {metric.latency_ms.toFixed(0)}ms
            </span>
            <span className="flex items-center gap-1">
              <Star className="size-2.5" />
              {metric.quality_score}/10
            </span>
            {metric.retries > 0 && (
              <span className="flex items-center gap-1 text-amber-500">
                <RotateCw className="size-2.5" />
                {metric.retries} {metric.retries === 1 ? "retry" : "retries"}
              </span>
            )}
          </div>

          {/* Rationale */}
          {metric.quality_rationale && (
            <p className="mt-1.5 text-[10px] text-zinc-400 leading-relaxed italic">
              &ldquo;{metric.quality_rationale}&rdquo;
            </p>
          )}
        </div>
      </div>
    </motion.div>
  );
}

function ResultPanel({
  result,
  intentText,
}: {
  result: ReturnType<typeof useIntentWs>["result"];
  intentText: string;
}) {
  if (!result) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 p-8 text-center text-muted-foreground">
        <Terminal className="size-8 opacity-20" />
        <p className="text-xs">Execution results will appear here</p>
      </div>
    );
  }

  const isSuccess = result.status === "success";
  const output = (result.metadata.output as string) || "";
  const outputSummary = (result.metadata.output_summary as string) || "";
  const agentMetrics = (result.metadata.agent_metrics as AgentMetric[]) || [];
  const execErrors = (result.metadata.errors as { agent_id: string; error: string }[]) || [];

  // Build a "rest" metadata object that excludes the fields we render specially
  const {
    output: _o,
    output_summary: _os,
    agent_metrics: _am,
    errors: _e,
    ...restMetadata
  } = result.metadata;
  const hasRestMetadata = Object.keys(restMetadata).length > 0;

  return (
    <div className="absolute inset-0 overflow-y-auto">
      <div className="p-4 space-y-4">
        {/* Status banner */}
        <div
          className={`flex items-center gap-2 rounded-lg p-3 ${
            isSuccess
              ? "bg-emerald-500/10 border border-emerald-500/20"
              : "bg-orange-500/10 border border-orange-500/20"
          }`}
        >
          {isSuccess ? (
            <CheckCircle2 className="size-5 text-emerald-400" />
          ) : (
            <AlertCircle className="size-5 text-orange-400" />
          )}
          <div>
            <p
              className={`text-sm font-semibold ${isSuccess ? "text-emerald-300" : "text-orange-300"}`}
            >
              {isSuccess ? "Execution Successful" : `Status: ${result.status}`}
            </p>
            {outputSummary && (
              <p className="mt-0.5 text-[11px] text-zinc-400">{outputSummary}</p>
            )}
          </div>
        </div>

        {/* Original intent reminder */}
        {intentText && (
          <div className="flex items-start gap-2.5 rounded-lg border border-zinc-800 bg-zinc-900/40 px-3 py-2.5">
            <Sparkles className="size-3.5 shrink-0 mt-0.5 text-blue-400" />
            <div className="min-w-0">
              <p className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider">
                Intent
              </p>
              <p className="mt-0.5 text-[12px] text-zinc-300 leading-relaxed">
                &ldquo;{intentText}&rdquo;
              </p>
            </div>
          </div>
        )}

        {/* Execution errors */}
        {execErrors.length > 0 && (
          <div className="space-y-2">
            {execErrors.map((err, i) => {
              // Parse IBAC restriction messages out of the error string
              // The server embeds them as a Python list repr inside the message
              let headline = err.error;
              let restrictions: string[] = [];

              const bracketMatch = err.error.match(/Restrictions:\s*\[(.+)\]$/);
              if (bracketMatch) {
                headline = err.error.slice(0, err.error.indexOf("Restrictions:")).trim();
                // Extract quoted strings from the Python-style list
                const rawList = bracketMatch[1];
                restrictions = [...rawList.matchAll(/"([^"]+)"/g)].map((m) => m[1]);
                // Deduplicate (IBAC retries often repeat the same message)
                restrictions = [...new Set(restrictions)];
              }

              return (
                <motion.div
                  key={`${err.agent_id}-${i}`}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3 }}
                  className="rounded-xl border border-red-500/20 bg-gradient-to-br from-red-500/5 via-transparent to-red-900/5"
                >
                  <div className="flex items-start gap-3 px-4 pt-3 pb-2">
                    <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-red-500/10">
                      <Shield className="size-4 text-red-400" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <h4 className="text-xs font-semibold text-red-300">
                          Execution Blocked
                        </h4>
                        <Badge
                          variant="outline"
                          className="text-[9px] px-1.5 py-0 border-red-500/20 text-red-400"
                        >
                          <Bot className="size-2.5 mr-1" />
                          {err.agent_id}
                        </Badge>
                      </div>
                      <p className="mt-1 text-[11px] text-zinc-300 leading-relaxed">
                        {headline}
                      </p>
                    </div>
                  </div>

                  {restrictions.length > 0 && (
                    <div className="mx-4 mb-3 rounded-lg border border-red-500/10 bg-red-950/20 p-2.5">
                      <p className="text-[9px] font-medium text-red-400/70 uppercase tracking-wider mb-1.5">
                        IBAC Restrictions
                      </p>
                      <ul className="space-y-1">
                        {restrictions.map((r, j) => (
                          <li
                            key={j}
                            className="flex items-start gap-2 text-[11px] text-zinc-400 leading-relaxed"
                          >
                            <XCircle className="size-3 shrink-0 mt-0.5 text-red-400/60" />
                            {r}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </motion.div>
              );
            })}
          </div>
        )}

        {/* Synthesised output — the main answer */}
        {output && (
          <div className="rounded-xl border border-violet-500/20 bg-gradient-to-br from-violet-500/5 via-transparent to-blue-500/5">
            <div className="flex items-center gap-2 px-4 pt-3 pb-2">
              <div className="flex size-6 items-center justify-center rounded-md bg-violet-500/10">
                <Quote className="size-3.5 text-violet-400" />
              </div>
              <h4 className="text-xs font-semibold text-violet-300">
                Synthesised Answer
              </h4>
            </div>
            <div className="px-4 pb-4">
              <div className="text-[12.5px] leading-relaxed text-zinc-200 whitespace-pre-wrap">
                {output}
              </div>
            </div>
          </div>
        )}

        {/* Agent metrics */}
        {agentMetrics.length > 0 && (
          <div>
            <div className="flex items-center gap-2 mb-2.5">
              <Gauge className="size-3.5 text-zinc-400" />
              <h4 className="text-xs font-semibold text-zinc-300">
                Agent Performance
              </h4>
              <Badge
                variant="outline"
                className="ml-auto text-[9px] px-1.5 py-0 border-zinc-700 text-zinc-500"
              >
                {agentMetrics.length} agent{agentMetrics.length !== 1 ? "s" : ""}
              </Badge>
            </div>
            <div className="space-y-2">
              {agentMetrics.map((m) => (
                <AgentMetricCard key={m.agent_id} metric={m} />
              ))}
            </div>
          </div>
        )}

        {/* Artifacts (raw JSON) */}
        {result.artifacts.length > 0 && (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <FileText className="size-3.5 text-zinc-400" />
              <h4 className="text-xs font-semibold text-zinc-300">Artifacts</h4>
            </div>
            {result.artifacts.map((art, i) => (
              <pre
                key={i}
                className="mb-2 max-h-64 overflow-auto rounded-md bg-zinc-900/80 border border-zinc-800 p-3 text-[11px] leading-relaxed text-zinc-300 font-mono"
              >
                {JSON.stringify(art, null, 2)}
              </pre>
            ))}
          </div>
        )}

        {/* Remaining metadata (if any) */}
        {hasRestMetadata && (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <MessageSquareText className="size-3.5 text-zinc-400" />
              <h4 className="text-xs font-semibold text-zinc-300">Metadata</h4>
            </div>
            <pre className="max-h-40 overflow-auto rounded-md bg-zinc-900/80 border border-zinc-800 p-3 text-[11px] leading-relaxed text-zinc-400 font-mono">
              {JSON.stringify(restMetadata, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Approval banner
// ---------------------------------------------------------------------------

function ApprovalBanner({
  plan,
  onApprove,
  onReject,
  onRenegotiate,
}: {
  plan: ExecutionPlan;
  onApprove: () => void;
  onReject: (reason: string) => void;
  onRenegotiate: (reason: string, hint?: Record<string, unknown>) => void;
}) {
  const [rejectOpen, setRejectOpen] = useState(false);
  const [renegOpen, setRenegOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [hint, setHint] = useState("");

  return (
    <>
      <motion.div
        initial={{ y: 20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.4, ease: "easeOut" }}
        className="mx-4 mb-3 rounded-xl border border-amber-500/30 bg-gradient-to-r from-amber-500/5 via-amber-500/10 to-amber-500/5 p-4"
      >
        <div className="flex items-start gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-amber-500/10">
            <Network className="size-5 text-amber-400" />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-amber-200">
              Execution Plan Requires Approval
            </h3>
            <p className="mt-1 text-xs text-zinc-400">
              {plan.flowDescription}
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {[...new Set(plan.participatingAgents)].map((a) => (
                <Badge key={a} variant="secondary" className="text-[10px]">
                  <Bot className="size-2.5 mr-1" />
                  {a}
                </Badge>
              ))}
            </div>
          </div>
          <div className="flex shrink-0 gap-2">
            <Button
              size="sm"
              className="gap-1.5 bg-emerald-600 hover:bg-emerald-700 text-white"
              onClick={onApprove}
            >
              <ThumbsUp className="size-3.5" /> Approve
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="gap-1.5 border-orange-500/30 text-orange-400 hover:bg-orange-500/10"
              onClick={() => setRenegOpen(true)}
            >
              <RefreshCw className="size-3.5" /> Renegotiate
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="gap-1.5 border-red-500/30 text-red-400 hover:bg-red-500/10"
              onClick={() => setRejectOpen(true)}
            >
              <ThumbsDown className="size-3.5" /> Reject
            </Button>
          </div>
        </div>
      </motion.div>

      {/* Reject dialog */}
      <Dialog open={rejectOpen} onOpenChange={setRejectOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject Plan</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <Label htmlFor="reject-reason">Reason</Label>
            <Textarea
              id="reject-reason"
              placeholder="Why are you rejecting this plan?"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRejectOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                onReject(reason);
                setRejectOpen(false);
                setReason("");
              }}
            >
              Reject
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Renegotiate dialog */}
      <Dialog open={renegOpen} onOpenChange={setRenegOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Renegotiate Plan</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div>
              <Label htmlFor="reneg-reason">Feedback</Label>
              <Textarea
                id="reneg-reason"
                placeholder="What should be changed?"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="reneg-hint">
                Hints{" "}
                <span className="text-muted-foreground">(JSON, optional)</span>
              </Label>
              <Input
                id="reneg-hint"
                placeholder='{"exclude_agents": ["x"], "max_cost": 100}'
                value={hint}
                onChange={(e) => setHint(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRenegOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                let parsedHint: Record<string, unknown> | undefined;
                try {
                  parsedHint = hint ? JSON.parse(hint) : undefined;
                } catch {
                  /* ignore */
                }
                onRenegotiate(reason, parsedHint);
                setRenegOpen(false);
                setReason("");
                setHint("");
              }}
            >
              Send Feedback
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

// ---------------------------------------------------------------------------
// Idle state
// ---------------------------------------------------------------------------

function IdleState({
  onSubmit,
}: {
  onSubmit: (text: string, assignedAgentId?: string) => void;
}) {
  const [input, setInput] = useState("");
  const [assignedAgentId, setAssignedAgentId] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = () => {
    const text = input.trim();
    if (!text) return;
    setInput("");
    onSubmit(text, assignedAgentId || undefined);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="flex h-full flex-col items-center justify-center px-8">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        className="max-w-xl w-full text-center"
      >
        <div className="mx-auto mb-6 flex size-16 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500/20 to-blue-500/20 border border-violet-500/20">
          <Network className="size-8 text-violet-400" />
        </div>

        <h1 className="text-2xl font-bold bg-gradient-to-r from-zinc-100 to-zinc-400 bg-clip-text text-transparent">
          Negotiation Flow
        </h1>
        <p className="mt-2 text-sm text-zinc-500 max-w-md mx-auto">
          Submit a natural-language intent and watch the coordinator decompose it,
          discover agents, negotiate an execution plan, and orchestrate execution
          in real-time.
        </p>

        {/* Agent validator selector */}
        <div className="mt-6 max-w-xs mx-auto text-left">
          <label className="block text-[11px] font-medium text-zinc-400 mb-1.5">
            Intent Agent <span className="text-zinc-600">(optional)</span>
          </label>
          <AgentSelect
            value={assignedAgentId}
            onChange={setAssignedAgentId}
            placeholder="Select intent agent…"
          />
        </div>

        <div className="mt-4 flex gap-2">
          <Textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Describe your intent… (Enter to send)"
            className="min-h-[56px] max-h-32 resize-none bg-zinc-900/50 border-zinc-700"
            rows={2}
          />
          <Button
            onClick={handleSubmit}
            disabled={!input.trim()}
            size="icon"
            className="shrink-0 self-end size-[56px] bg-violet-600 hover:bg-violet-700"
          >
            <Send className="size-5" />
          </Button>
        </div>

        <div className="mt-6 flex flex-wrap justify-center gap-2 text-[11px] text-zinc-600">
          {[
            "Search for recent financial reports",
            "Analyze customer sentiment data",
            "Generate a summary of Q4 metrics",
          ].map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => {
                setInput(example);
                textareaRef.current?.focus();
              }}
              className="rounded-full border border-zinc-800 px-3 py-1 hover:border-zinc-600 hover:text-zinc-400 transition-colors"
            >
              {example}
            </button>
          ))}
        </div>
      </motion.div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function IntentPage() {
  const {
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
    assignedAgentId,
    submitIntent,
    sendDecision,
    reset,
  } = useIntentWs();

  const isIdle = currentPhase === "idle";

  return (
    <>
      <AppHeader
        breadcrumbs={[
          { label: "Dashboard", href: "/" },
          { label: "Negotiation Flow" },
        ]}
      />

      {isIdle ? (
        <div className="h-[calc(100vh-3.5rem)]">
          <IdleState onSubmit={(text, assignedAgentId) => submitIntent(text, undefined, assignedAgentId)} />
        </div>
      ) : (
        <div className="flex h-[calc(100vh-3.5rem)] flex-col">
          {/* Phase pipeline */}
          <PhasePipeline currentPhase={currentPhase} progress={progress} />
          <Separator />

          {/* Approval banner */}
          <AnimatePresence>
            {awaitingApproval && plan && (
              <ApprovalBanner
                plan={plan}
                onApprove={() => sendDecision("approve")}
                onReject={(reason) => sendDecision("reject", reason)}
                onRenegotiate={(reason, hint) =>
                  sendDecision("renegotiate", reason, hint)
                }
              />
            )}
          </AnimatePresence>

          {/* Main content – three-panel layout */}
          <div className="flex flex-1 overflow-hidden">
            <ResizablePanelGroup orientation="horizontal">
              {/* Left: Execution graph */}
              <ResizablePanel defaultSize={50} minSize={25}>
                <div className="flex h-full flex-col min-w-0">
                  <div className="flex items-center gap-2 border-b border-zinc-800 px-4 py-2.5">
                    <Network className="size-4 text-violet-400" />
                    <span className="text-xs font-semibold text-zinc-300">
                      Execution Graph
                    </span>
                    {plan && (
                      <Badge variant="outline" className="ml-auto text-[9px] px-1.5 py-0">
                        {plan.steps.length} step{plan.steps.length !== 1 ? "s" : ""}
                      </Badge>
                    )}
                  </div>
                  <div className="flex-1">
                    <ExecutionGraph
                      plan={plan}
                      agents={agents}
                      currentPhase={currentPhase}
                      result={result}
                      assignedAgentId={assignedAgentId}
                    />
                  </div>
                </div>
              </ResizablePanel>

              <ResizableHandle withHandle />

              {/* Center: Event timeline + results */}
              <ResizablePanel defaultSize={30} minSize={20}>
                <div className="flex h-full flex-col min-w-0">
                  <Tabs defaultValue="timeline" className="flex flex-1 flex-col">
                    <div className="border-b border-zinc-800 px-4">
                      <TabsList className="h-9 bg-transparent">
                        <TabsTrigger value="timeline" className="text-xs gap-1.5 data-[state=active]:bg-zinc-800">
                          <Activity className="size-3" /> Timeline
                          <Badge variant="secondary" className="ml-1 text-[9px] px-1.5 py-0 h-4">
                            {events.length}
                          </Badge>
                        </TabsTrigger>
                        <TabsTrigger value="results" className="text-xs gap-1.5 data-[state=active]:bg-zinc-800">
                          <Terminal className="size-3" /> Results
                          {result && (
                            <span
                              className={`ml-1 size-2 rounded-full ${
                                result.status === "success" ? "bg-emerald-400" : "bg-orange-400"
                              }`}
                            />
                          )}
                        </TabsTrigger>
                      </TabsList>
                    </div>
                    <TabsContent value="timeline" className="flex-1 mt-0 relative overflow-hidden">
                      <EventTimeline events={events} />
                    </TabsContent>
                    <TabsContent value="results" className="flex-1 mt-0 relative overflow-hidden">
                      <ResultPanel result={result} intentText={intentText} />
                    </TabsContent>
                  </Tabs>
                </div>
              </ResizablePanel>
            </ResizablePanelGroup>

            {/* Right: Agent sidebar */}
            <div className="flex w-[300px] shrink-0 flex-col border-l border-zinc-800">
              <div className="flex items-center gap-2 border-b border-zinc-800 px-4 py-2.5">
                <Bot className="size-4 text-emerald-400" />
                <span className="text-xs font-semibold text-zinc-300">
                  Agents
                </span>
                <Badge variant="outline" className="ml-auto text-[9px] px-1.5 py-0">
                  {agents.size}
                </Badge>
              </div>
              <div className="relative flex-1 overflow-hidden">
                <AgentCards agents={agents} />
              </div>
            </div>
          </div>

          {/* Bottom bar */}
          <div className="flex items-center justify-between border-t border-zinc-800 px-4 py-2">
            <div className="flex items-center gap-3">
              <StatusDot status={status} />
              {sessionId && (
                <Badge
                  variant="outline"
                  className="font-mono text-[9px] text-zinc-500 border-zinc-700"
                >
                  {sessionId.slice(0, 28)}…
                </Badge>
              )}
              {intentText && (
                <span className="text-[11px] text-zinc-500 truncate max-w-[300px]">
                  &ldquo;{intentText}&rdquo;
                </span>
              )}
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={reset}
              className="gap-1.5 text-xs text-zinc-500 hover:text-zinc-300"
            >
              <RotateCcw className="size-3" /> New Session
            </Button>
          </div>
        </div>
      )}
    </>
  );
}
