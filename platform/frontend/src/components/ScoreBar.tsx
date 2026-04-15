import { clsx } from "clsx";

interface ScoreBarProps {
  score: number;
  showLabel?: boolean;
  className?: string;
}

function getScoreColor(score: number): string {
  if (score >= 80) return "bg-green-500";
  if (score >= 60) return "bg-emerald-400";
  if (score >= 40) return "bg-yellow-400";
  if (score >= 20) return "bg-orange-400";
  return "bg-red-400";
}

function getScoreTextColor(score: number): string {
  if (score >= 80) return "text-green-700";
  if (score >= 60) return "text-emerald-700";
  if (score >= 40) return "text-yellow-700";
  if (score >= 20) return "text-orange-700";
  return "text-red-700";
}

export function ScoreBar({ score, showLabel = true, className }: ScoreBarProps) {
  const clamped = Math.max(0, Math.min(100, score));

  return (
    <div className={clsx("flex items-center gap-2", className)}>
      <div className="h-2 w-16 overflow-hidden rounded-full bg-gray-200">
        <div
          className={clsx("h-full rounded-full transition-all", getScoreColor(clamped))}
          style={{ width: `${clamped}%` }}
        />
      </div>
      {showLabel && (
        <span className={clsx("text-xs font-medium", getScoreTextColor(clamped))}>
          {/*
            Regression finding 50: the label used to render whatever
            precision the backend happened to send. For Dashboard's
            `avg_relevance_score` that's a float (e.g. 39.65) so the
            ScoreBar showed "39.65" while the Analytics MetricCard
            rounded the exact same value to 40 via .toFixed(0). Same
            number, two representations, user-confusing.

            toFixed(1) standardises across every ScoreBar consumer
            (Dashboard averages, job relevance, resume ATS scores) at
            one decimal — same precision the role-cluster progress
            bars already use elsewhere in the app.
          */}
          {clamped.toFixed(1)}
        </span>
      )}
    </div>
  );
}
