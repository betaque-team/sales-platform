import { clsx } from "clsx";
import type { ReactNode } from "react";

type BadgeVariant =
  | "default"
  | "primary"
  | "success"
  | "warning"
  | "danger"
  | "info"
  | "gray";

interface BadgeProps {
  children: ReactNode;
  variant?: BadgeVariant;
  className?: string;
}

const variantClasses: Record<BadgeVariant, string> = {
  default:
    "bg-gray-100 text-gray-700 ring-gray-200",
  primary:
    "bg-primary-50 text-primary-700 ring-primary-200",
  success:
    "bg-green-50 text-green-700 ring-green-200",
  warning:
    "bg-yellow-50 text-yellow-700 ring-yellow-200",
  danger:
    "bg-red-50 text-red-700 ring-red-200",
  info:
    "bg-blue-50 text-blue-700 ring-blue-200",
  gray:
    "bg-gray-50 text-gray-600 ring-gray-200",
};

export function Badge({
  children,
  variant = "default",
  className,
}: BadgeProps) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset",
        variantClasses[variant],
        className
      )}
    >
      {children}
    </span>
  );
}
