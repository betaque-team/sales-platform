import type { JobStatus } from "@/lib/types";
import { Badge } from "./Badge";

const statusConfig: Record<
  JobStatus,
  { label: string; variant: "info" | "warning" | "success" | "danger" | "gray" }
> = {
  new: { label: "New", variant: "info" },
  under_review: { label: "Under Review", variant: "warning" },
  accepted: { label: "Accepted", variant: "success" },
  rejected: { label: "Rejected", variant: "danger" },
  expired: { label: "Expired", variant: "gray" },
};

interface StatusBadgeProps {
  status: JobStatus;
  className?: string;
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const config = statusConfig[status] || { label: status, variant: "gray" as const };
  return (
    <Badge variant={config.variant} className={className}>
      {config.label}
    </Badge>
  );
}
