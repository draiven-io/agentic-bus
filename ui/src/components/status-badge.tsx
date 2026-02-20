import { Badge } from "@/components/ui/badge";
import type { AgentStatus, ManagedAgentStatus } from "@/lib/types";

const statusVariants: Record<
  AgentStatus | ManagedAgentStatus,
  "default" | "secondary" | "destructive" | "outline"
> = {
  approved: "default",
  active: "default",
  pending: "secondary",
  draft: "secondary",
  rejected: "destructive",
  revoked: "destructive",
  disabled: "outline",
};

const statusLabels: Record<AgentStatus | ManagedAgentStatus, string> = {
  approved: "Approved",
  active: "Active",
  pending: "Pending",
  draft: "Draft",
  rejected: "Rejected",
  revoked: "Revoked",
  disabled: "Disabled",
};

interface StatusBadgeProps {
  status: AgentStatus | ManagedAgentStatus;
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
