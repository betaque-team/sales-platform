/**
 * Remote-policy vocabulary — frontend mirror of
 * `app/utils/remote_policy.py`.
 *
 * The legacy `geography_bucket` enum (`global_remote` / `usa_only` /
 * `uae_only` / `""`) confused the team. This module is the single
 * place that defines:
 *
 *   - the new vocabulary (`RemotePolicy`),
 *   - human-readable labels and short-form labels,
 *   - badge colours so analytics + filter chips stay consistent,
 *   - a helper that translates legacy values for any read path that
 *     still encounters them during the transition window,
 *   - a country-code → display-name map for rendering
 *     `country_restricted` rows ("USA-restricted remote", etc.).
 *
 * Keep in sync with the backend module — both ship together.
 */

export type RemotePolicy =
  | "worldwide"
  | "country_restricted"
  | "region_restricted"
  | "hybrid"
  | "onsite"
  | "unknown";

export const ALL_REMOTE_POLICIES: RemotePolicy[] = [
  "worldwide",
  "country_restricted",
  "region_restricted",
  "hybrid",
  "onsite",
  "unknown",
];

/**
 * Long-form labels. Used in headings, filter dropdowns, badges where
 * there's room. Match the backend `POLICY_LABELS` values verbatim.
 */
export const REMOTE_POLICY_LABELS: Record<RemotePolicy, string> = {
  worldwide: "Worldwide remote",
  country_restricted: "Country-restricted remote",
  region_restricted: "Region-restricted remote",
  hybrid: "Hybrid",
  onsite: "On-site",
  unknown: "Needs classification",
};

/**
 * Short labels for compact UI surfaces — e.g. the chip on the job
 * card where vertical space is tight. Match
 * `POLICY_SHORT_LABELS` on the backend.
 */
export const REMOTE_POLICY_SHORT_LABELS: Record<RemotePolicy, string> = {
  worldwide: "Worldwide",
  country_restricted: "Country-only",
  region_restricted: "Region-only",
  hybrid: "Hybrid",
  onsite: "On-site",
  unknown: "Unknown",
};

/**
 * Hex colors for chart segments + badge accents. Greens/blues for
 * accessible-from-anywhere policies, oranges for restricted, pink
 * for "needs human review".
 */
export const REMOTE_POLICY_COLORS: Record<RemotePolicy, string> = {
  worldwide: "#10b981", // emerald
  country_restricted: "#f97316", // orange
  region_restricted: "#f59e0b", // amber
  hybrid: "#3b82f6", // blue
  onsite: "#6366f1", // indigo
  unknown: "#94a3b8", // slate
};

// Country code → display name. Kept short — only the codes the
// classifier currently recognises plus a few that the team picks
// from filter dropdowns. Add more as `country_restricted` rows
// surface them.
export const COUNTRY_NAMES: Record<string, string> = {
  US: "United States",
  AE: "United Arab Emirates",
  GB: "United Kingdom",
  CA: "Canada",
  IN: "India",
  DE: "Germany",
  PH: "Philippines",
  MX: "Mexico",
  IE: "Ireland",
  PL: "Poland",
  AU: "Australia",
  BR: "Brazil",
  SE: "Sweden",
  NL: "Netherlands",
  CH: "Switzerland",
  IL: "Israel",
  EE: "Estonia",
  SG: "Singapore",
  ES: "Spain",
  FR: "France",
  JP: "Japan",
  KR: "South Korea",
  NG: "Nigeria",
  ZA: "South Africa",
  CO: "Colombia",
  AR: "Argentina",
  CL: "Chile",
  RO: "Romania",
  TR: "Turkey",
  PT: "Portugal",
};

/**
 * Render the most readable label for a (policy, countries) pair.
 *
 * Special-cases `country_restricted` so the badge says "USA-restricted
 * remote" instead of the generic "Country-restricted remote" when
 * exactly one country is listed. Two-country lists render as "US/CA-
 * restricted remote"; three or more fall back to the generic label
 * with a count ("3 countries restricted").
 */
export function renderRemotePolicyLabel(
  policy: RemotePolicy | string,
  countries?: string[] | null,
): string {
  const codes = (countries ?? []).filter(Boolean);
  if (policy === "country_restricted" && codes.length > 0) {
    if (codes.length === 1) {
      const name = COUNTRY_NAMES[codes[0]] ?? codes[0];
      return `${name}-restricted remote`;
    }
    if (codes.length <= 2) {
      return `${codes.join("/")}-restricted remote`;
    }
    return `${codes.length} countries restricted`;
  }
  return (
    REMOTE_POLICY_LABELS[policy as RemotePolicy] ??
    REMOTE_POLICY_LABELS.unknown
  );
}

/**
 * Translation from the legacy `geography_bucket` value to the new
 * `(policy, countries)` pair. Used by any read path that still
 * encounters a row classified before the migration ran. Mirrors the
 * backend `LEGACY_TO_POLICY` / `LEGACY_TO_COUNTRIES` tables.
 */
export function legacyToRemotePolicy(legacy: string): {
  policy: RemotePolicy;
  countries: string[];
} {
  switch (legacy) {
    case "global_remote":
      return { policy: "worldwide", countries: [] };
    case "usa_only":
      return { policy: "country_restricted", countries: ["US"] };
    case "uae_only":
      return { policy: "country_restricted", countries: ["AE"] };
    default:
      return { policy: "unknown", countries: [] };
  }
}
