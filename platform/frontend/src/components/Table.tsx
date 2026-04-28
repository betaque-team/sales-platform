import { clsx } from "clsx";
import type { ReactNode, ThHTMLAttributes, TdHTMLAttributes } from "react";

export function Table({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  // F260 regression fix: Mac mini users without a touchpad can't
  // swipe-scroll horizontally, and macOS hides the scrollbar by
  // default unless touched. The Jobs table is wider than ~1280px
  // viewports, so half the columns become invisible-and-untouchable
  // (feedback 9409b8b2 — "I cannot go through what is at the right
  // side of that page"). Two fixes layered here:
  //   1. ``[scrollbar-gutter:stable]`` reserves the gutter so the
  //      bar is visible even when not actively scrolling. Modern
  //      Safari + Chrome + Firefox all honour this.
  //   2. ``[&::-webkit-scrollbar]`` styles force a 10px bar on
  //      WebKit (macOS Safari) where the OS-level "auto-hide
  //      scrollbars" preference would otherwise dominate.
  // Net: a visible scrollbar appears at the bottom of every wide
  // table — the affordance for "drag this to see more →" stays on
  // screen, no mouse hover required.
  return (
    <div
      className={clsx(
        "overflow-x-auto",
        "[scrollbar-gutter:stable]",
        "[&::-webkit-scrollbar]:h-2 [&::-webkit-scrollbar]:bg-gray-100",
        "[&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-gray-400",
        className,
      )}
    >
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
