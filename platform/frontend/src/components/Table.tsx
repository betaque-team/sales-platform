import { clsx } from "clsx";
import type { ReactNode, ThHTMLAttributes, TdHTMLAttributes } from "react";

export function Table({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={clsx("overflow-x-auto", className)}>
      <table className="min-w-full divide-y divide-gray-200">
        {children}
      </table>
    </div>
  );
}

export function TableHeader({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <thead className={clsx("bg-gray-50", className)}>
      {children}
    </thead>
  );
}

export function TableBody({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <tbody className={clsx("divide-y divide-gray-200 bg-white", className)}>
      {children}
    </tbody>
  );
}

export function TableRow({
  children,
  className,
  onClick,
  clickable = false,
}: {
  children: ReactNode;
  className?: string;
  onClick?: () => void;
  clickable?: boolean;
}) {
  return (
    <tr
      className={clsx(
        clickable && "cursor-pointer hover:bg-gray-50 transition-colors",
        className
      )}
      onClick={onClick}
    >
      {children}
    </tr>
  );
}

export function TableHead({
  children,
  className,
  ...props
}: ThHTMLAttributes<HTMLTableCellElement> & { children?: ReactNode }) {
  return (
    <th
      className={clsx(
        "px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500",
        className
      )}
      {...props}
    >
      {children}
    </th>
  );
}

export function TableCell({
  children,
  className,
  ...props
}: TdHTMLAttributes<HTMLTableCellElement> & { children?: ReactNode }) {
  return (
    <td
      className={clsx(
        "whitespace-nowrap px-4 py-3 text-sm text-gray-700",
        className
      )}
      {...props}
    >
      {children}
    </td>
  );
}
