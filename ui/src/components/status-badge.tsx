import { Badge } from "@/components/ui/badge";
import type { AgentStatus, ManagedAgentStatus, EphemeralAgentStatus, MCPServerStatus } from "@/lib/types";

type AnyStatus = AgentStatus | ManagedAgentStatus | EphemeralAgentStatus | MCPServerStatus;

const statusVariants: Record<
  AnyStatus,
  "default" | "secondary" | "destructive" | "outline"
> = {
  approved: "default",
  active: "default",
  online: "default",
  pending: "secondary",
  draft: "secondary",
  rejected: "destructive",
  revoked: "destructive",
  disabled: "outline",
};

const statusLabels: Record<AnyStatus, string> = {
  approved: "Approved",
  active: "Active",
  online: "Online",
  pending: "Pending",
  draft: "Draft",
  rejected: "Rejected",
  revoked: "Revoked",
  disabled: "Disabled",
};

interface StatusBadgeProps {
  status: AnyStatus;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  return (
    <Badge variant={statusVariants[status]}>
      {statusLabels[status]}
    </Badge>
  );
}

// Severity badge for audit logs
const severityVariants: Record<
  string,
  "default" | "secondary" | "destructive" | "outline"
> = {
  info: "secondary",
  warning: "outline",
  error: "destructive",
  critical: "destructive",
};

export function SeverityBadge({ severity }: { severity: string }) {
  return (
    <Badge variant={severityVariants[severity] ?? "secondary"}>
      {severity}
    </Badge>
  );
}
