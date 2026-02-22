"use client";

import { useRef, useEffect, useState, type KeyboardEvent } from "react";
import {
  Send,
  Loader2,
  CheckCircle2,
  XCircle,
  MessageSquare,
  Bot,
  Zap,
  ThumbsUp,
  ThumbsDown,
  RefreshCw,
  Trash2,
  WifiOff,
  Wifi,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Play,
  CircleDot,
} from "lucide-react";

import { AppHeader } from "@/components/app-header";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";

import {
  useIntentWs,
  type ChatMessage,
  type ConnectionStatus,
} from "@/hooks/use-intent-ws";
import type { OfferPayload, CompletePayload } from "@/lib/protocol";

// ---------------------------------------------------------------------------
// Status indicator
// ---------------------------------------------------------------------------

function StatusDot({ status }: { status: ConnectionStatus }) {
  const cfg: Record<ConnectionStatus, { color: string; label: string; Icon: typeof Wifi }> = {
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
// JSON viewer (collapsible)
// ---------------------------------------------------------------------------

function JsonViewer({ data, label }: { data: unknown; label?: string }) {
  const [open, setOpen] = useState(false);
  if (!data || (typeof data === "object" && Object.keys(data as object).length === 0))
    return null;

  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        {open ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />}
        {label ?? "Details"}
      </button>
      {open && (
        <pre className="mt-1 max-h-60 overflow-auto rounded-md bg-muted/50 p-2 text-xs leading-relaxed">
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chat bubble components
// ---------------------------------------------------------------------------

function UserBubble({ msg }: { msg: ChatMessage }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-primary-foreground">
        <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
        <span className="mt-1 block text-[10px] opacity-60">
          {new Date(msg.timestamp).toLocaleTimeString()}
        </span>
      </div>
    </div>
  );
}

function SystemBubble({ msg }: { msg: ChatMessage }) {
  return (
    <div className="flex justify-center">
      <span className="rounded-full bg-muted px-3 py-1 text-xs text-muted-foreground">
        {msg.content}
      </span>
    </div>
  );
}

function ErrorBubble({ msg }: { msg: ChatMessage }) {
  return (
    <div className="flex justify-center">
      <span className="flex items-center gap-1.5 rounded-full bg-destructive/10 px-3 py-1 text-xs text-destructive">
        <AlertCircle className="size-3" />
        {msg.content}
      </span>
    </div>
  );
}

function OfferBubble({ msg }: { msg: ChatMessage }) {
  const payload = msg.envelope?.payload as unknown as OfferPayload | undefined;
  return (
    <div className="flex justify-start">
      <Card className="max-w-[85%] border-blue-500/30 bg-blue-500/5">
        <CardHeader className="pb-2">
          <div className="flex items-center gap-2">
            <Bot className="size-4 text-blue-400" />
            <CardTitle className="text-sm font-medium">Agent Offer</CardTitle>
            <Badge variant="outline" className="text-[10px]">
              {payload?.capability_id}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="pb-3">
          <p className="text-sm text-muted-foreground">{msg.content}</p>
          {payload && (
            <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
              {payload.estimated_cost != null && (
                <Badge variant="secondary">Cost: {payload.estimated_cost}</Badge>
              )}
              {payload.estimated_latency != null && (
                <Badge variant="secondary">Latency: {payload.estimated_latency}s</Badge>
              )}
              {payload.participating_agents?.length > 0 && (
                <Badge variant="secondary">
                  Agents: {payload.participating_agents.length}
                </Badge>
              )}
            </div>
          )}
          <JsonViewer data={payload?.constraints} label="Constraints" />
          <JsonViewer data={payload?.output_schema} label="Output schema" />
          <span className="mt-2 block text-[10px] text-muted-foreground">
            {new Date(msg.timestamp).toLocaleTimeString()}
          </span>
        </CardContent>
      </Card>
    </div>
  );
}

function PlanBubble({
  msg,
  onApprove,
  onReject,
  onRenegotiate,
}: {
  msg: ChatMessage;
  onApprove: () => void;
  onReject: (reason: string) => void;
  onRenegotiate: (reason: string, hint?: Record<string, unknown>) => void;
}) {
  const payload = msg.envelope?.payload as unknown as OfferPayload | undefined;
  const [rejectOpen, setRejectOpen] = useState(false);
  const [renegOpen, setRenegOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [hint, setHint] = useState("");

  return (
    <>
      <div className="flex justify-start">
        <Card className="max-w-[90%] border-amber-500/40 bg-amber-500/5">
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <Zap className="size-4 text-amber-400" />
              <CardTitle className="text-sm font-medium">
                Execution Plan Proposed
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="pb-3">
            <p className="text-sm">{msg.content}</p>

            {payload?.participating_agents && payload.participating_agents.length > 0 && (
              <div className="mt-3">
                <span className="text-xs font-medium text-muted-foreground">
                  Participating agents:
                </span>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {payload.participating_agents.map((a) => (
                    <Badge key={a} variant="secondary" className="text-[11px]">
                      {a}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            <JsonViewer data={payload?.composition_plan} label="Composition plan" />
            <JsonViewer data={payload?.constraints} label="Constraints" />

            {msg.awaitingDecision && (
              <div className="mt-4 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="default"
                  className="gap-1.5"
                  onClick={onApprove}
                >
                  <ThumbsUp className="size-3.5" /> Approve
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  className="gap-1.5"
                  onClick={() => setRejectOpen(true)}
                >
                  <ThumbsDown className="size-3.5" /> Reject
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-1.5"
                  onClick={() => setRenegOpen(true)}
                >
                  <RefreshCw className="size-3.5" /> Renegotiate
                </Button>
              </div>
            )}

            <span className="mt-2 block text-[10px] text-muted-foreground">
              {new Date(msg.timestamp).toLocaleTimeString()}
            </span>
          </CardContent>
        </Card>
      </div>

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
              <Label htmlFor="reneg-reason">Feedback / reason</Label>
              <Textarea
                id="reneg-reason"
                placeholder="What should be changed?"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="reneg-hint">
                Renegotiation hints{" "}
                <span className="text-muted-foreground">(JSON, optional)</span>
              </Label>
              <Input
                id="reneg-hint"
                placeholder='e.g., {"exclude_agents": ["agent-x"], "max_cost": 100}'
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
                  // ignore bad JSON
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

function AcceptBubble({ msg }: { msg: ChatMessage }) {
  return (
    <div className="flex justify-start">
      <div className="flex max-w-[80%] items-start gap-2 rounded-2xl rounded-bl-md bg-green-500/10 px-4 py-2.5">
        <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-green-500" />
        <div>
          <p className="text-sm">{msg.content}</p>
          <span className="mt-1 block text-[10px] text-muted-foreground">
            {new Date(msg.timestamp).toLocaleTimeString()}
          </span>
        </div>
      </div>
    </div>
  );
}

function RejectBubble({ msg }: { msg: ChatMessage }) {
  return (
    <div className="flex justify-start">
      <div className="flex max-w-[80%] items-start gap-2 rounded-2xl rounded-bl-md bg-destructive/10 px-4 py-2.5">
        <XCircle className="mt-0.5 size-4 shrink-0 text-destructive" />
        <div>
          <p className="text-sm">{msg.content}</p>
          <JsonViewer data={msg.envelope?.payload} label="Details" />
          <span className="mt-1 block text-[10px] text-muted-foreground">
            {new Date(msg.timestamp).toLocaleTimeString()}
          </span>
        </div>
      </div>
    </div>
  );
}

function ExecuteBubble({ msg }: { msg: ChatMessage }) {
  return (
    <div className="flex justify-start">
      <div className="flex max-w-[80%] items-start gap-2 rounded-2xl rounded-bl-md bg-violet-500/10 px-4 py-2.5">
        <Play className="mt-0.5 size-4 shrink-0 text-violet-400" />
        <div>
          <p className="text-sm">{msg.content}</p>
          <JsonViewer data={msg.envelope?.payload} label="Execution plan" />
          <span className="mt-1 block text-[10px] text-muted-foreground">
            {new Date(msg.timestamp).toLocaleTimeString()}
          </span>
        </div>
      </div>
    </div>
  );
}

function CompleteBubble({ msg }: { msg: ChatMessage }) {
  const payload = msg.envelope?.payload as unknown as CompletePayload | undefined;
  const isSuccess = payload?.status === "success";

  return (
    <div className="flex justify-start">
      <Card
        className={`max-w-[90%] ${isSuccess ? "border-green-500/40 bg-green-500/5" : "border-orange-500/40 bg-orange-500/5"}`}
      >
        <CardHeader className="pb-2">
          <div className="flex items-center gap-2">
            <CheckCircle2
              className={`size-4 ${isSuccess ? "text-green-500" : "text-orange-400"}`}
            />
            <CardTitle className="text-sm font-medium">Result</CardTitle>
            <Badge variant={isSuccess ? "default" : "secondary"} className="text-[10px]">
              {payload?.status ?? "complete"}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="pb-3">
          <p className="text-sm">{msg.content}</p>

          {payload?.artifacts && payload.artifacts.length > 0 && (
            <div className="mt-2">
              <span className="text-xs font-medium text-muted-foreground">
                Artifacts:
              </span>
              {payload.artifacts.map((art, i) => (
                <pre
                  key={i}
                  className="mt-1 max-h-80 overflow-auto rounded-md bg-muted/50 p-3 text-xs leading-relaxed"
                >
                  {JSON.stringify(art, null, 2)}
                </pre>
              ))}
            </div>
          )}

          <JsonViewer data={payload?.metadata} label="Metadata" />

          <span className="mt-2 block text-[10px] text-muted-foreground">
            {new Date(msg.timestamp).toLocaleTimeString()}
          </span>
        </CardContent>
      </Card>
    </div>
  );
}

function DissolveBubble({ msg }: { msg: ChatMessage }) {
  return (
    <div className="flex justify-center">
      <span className="flex items-center gap-1.5 rounded-full bg-muted px-3 py-1 text-xs text-muted-foreground">
        <CircleDot className="size-3" />
        Session ended — {msg.content}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Message renderer
// ---------------------------------------------------------------------------

function ChatBubble({
  msg,
  onApprove,
  onReject,
  onRenegotiate,
}: {
  msg: ChatMessage;
  onApprove: () => void;
  onReject: (reason: string) => void;
  onRenegotiate: (reason: string, hint?: Record<string, unknown>) => void;
}) {
  switch (msg.role) {
    case "user":
      return <UserBubble msg={msg} />;
    case "system":
      return <SystemBubble msg={msg} />;
    case "error":
      return <ErrorBubble msg={msg} />;
    case "offer":
      return <OfferBubble msg={msg} />;
    case "plan":
      return (
        <PlanBubble
          msg={msg}
          onApprove={onApprove}
          onReject={onReject}
          onRenegotiate={onRenegotiate}
        />
      );
    case "accept":
      return <AcceptBubble msg={msg} />;
    case "reject":
      return <RejectBubble msg={msg} />;
    case "execute":
      return <ExecuteBubble msg={msg} />;
    case "complete":
      return <CompleteBubble msg={msg} />;
    case "dissolve":
      return <DissolveBubble msg={msg} />;
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function IntentPage() {
  const {
    status,
    messages,
    sessionId,
    submitIntent,
    sendDecision,
    clearChat,
  } = useIntentWs();

  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // auto-scroll to bottom on new messages
  useEffect(() => {
    const el = scrollRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages]);

  const handleSubmit = () => {
    const text = input.trim();
    if (!text) return;
    setInput("");
    submitIntent(text);
    // refocus textarea
    setTimeout(() => textareaRef.current?.focus(), 50);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const isConnected = status === "connected" || status === "connecting";

  return (
    <>
      <AppHeader
        breadcrumbs={[
          { label: "Dashboard", href: "/" },
          { label: "Intent Chat" },
        ]}
      />

      <div className="flex h-[calc(100vh-3.5rem)] flex-col">
        {/* Toolbar */}
        <div className="flex items-center justify-between border-b px-4 py-2">
          <div className="flex items-center gap-3">
            <MessageSquare className="size-5 text-primary" />
            <div>
              <h1 className="text-sm font-semibold">Intent Chat</h1>
              <p className="text-xs text-muted-foreground">
                Submit natural-language intentions and follow the coordinator flow
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <StatusDot status={status} />
            {sessionId && (
              <Badge variant="outline" className="font-mono text-[10px]">
                {sessionId.slice(0, 24)}…
              </Badge>
            )}
            <Button variant="ghost" size="sm" onClick={clearChat} className="gap-1.5">
              <Trash2 className="size-3.5" /> Clear
            </Button>
          </div>
        </div>

        {/* Messages */}
        <ScrollArea className="flex-1 px-4" ref={scrollRef}>
          <div className="mx-auto max-w-3xl space-y-4 py-6">
            {messages.length === 0 && (
              <div className="flex flex-col items-center justify-center gap-3 pt-24 text-center text-muted-foreground">
                <MessageSquare className="size-12 opacity-30" />
                <p className="text-sm">
                  Type an intent below to start a conversation with the coordinator.
                </p>
                <p className="max-w-md text-xs">
                  The coordinator will decompose your intent, discover capable agents,
                  negotiate an execution plan, and present it for your approval before
                  executing.
                </p>
              </div>
            )}

            {messages.map((msg) => (
              <ChatBubble
                key={msg.id}
                msg={msg}
                onApprove={() => sendDecision("approve")}
                onReject={(reason) => sendDecision("reject", reason)}
                onRenegotiate={(reason, hint) =>
                  sendDecision("renegotiate", reason, hint)
                }
              />
            ))}
          </div>
        </ScrollArea>

        <Separator />

        {/* Input */}
        <div className="px-4 py-3">
          <div className="mx-auto flex max-w-3xl gap-2">
            <Textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                isConnected
                  ? "Waiting for session to complete…"
                  : "Describe your intent… (Enter to send, Shift+Enter for newline)"
              }
              disabled={isConnected}
              className="min-h-[44px] max-h-32 resize-none"
              rows={1}
            />
            <Button
              onClick={handleSubmit}
              disabled={!input.trim() || isConnected}
              size="icon"
              className="shrink-0 self-end"
            >
              {status === "connecting" ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Send className="size-4" />
              )}
            </Button>
          </div>
        </div>
      </div>
    </>
  );
}
