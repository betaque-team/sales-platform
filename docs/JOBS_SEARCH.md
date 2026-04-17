# Jobs search — boolean syntax + saved filter presets

The All Jobs page (`/jobs`) supports two power-user features that the
default UI hints at but doesn't dwell on:

1. **Boolean search syntax** in the search bar (Round 72 / F240)
2. **Saved filter presets** via the Saved (★) dropdown next to the
   search bar (Round 72 / F241)

This doc covers both.

---

## Boolean search syntax

The search bar previously did a single ILIKE substring match across
job title + company name + location. Now it ALSO recognizes boolean
operators when you use them.

### Bare queries (no operators) — unchanged

```
bitwarden
senior security engineer
```

These work exactly as before — substring match across title, company,
and location columns. No behavior change for users not opting in.

### Boolean syntax (opt-in via operators)

| Syntax | Meaning |
|---|---|
| `cloud kubernetes` | Both must match (implicit AND between adjacent terms) |
| `cloud AND kubernetes` | Same as above, explicit |
| `cloud OR kubernetes` | Either matches |
| `"site reliability"` | Match the literal phrase as one token |
| `security NOT manager` | Match `security` but exclude rows that also match `manager` |
| `-manager security` | Same as above (Google-style minus prefix) |
| `(cloud OR kubernetes) AND remote NOT manager` | Grouping + composition |

**Operator precedence** (highest → lowest): `NOT` > `AND` > `OR`.
Matches the universal SQL/programming convention.

**Operators are case-sensitive when uppercase** (`AND`, `OR`, `NOT`).
Lowercase `and` / `or` / `not` are treated as plain search terms so a
query like `arts and crafts` doesn't accidentally trigger boolean
mode.

### Examples

- **Find remote infra jobs that aren't management roles**:
  `(cloud OR kubernetes OR devops) AND remote NOT manager`

- **Find security postings at fintech companies but exclude
  contractor roles**:
  `security AND fintech NOT contract`

- **Find a specific multi-word title**:
  `"site reliability engineer" -intern`

### Syntax errors

Bad syntax returns HTTP 400 with a useful detail:

```
GET /api/v1/jobs?search=security AND
→ 400 {"detail": "Search syntax error: Trailing AND with no right-hand operand"}
```

The frontend shows this inline above the results table. Common errors:

- `"unbalanced` — missing closing quote
- `security AND` — trailing operator
- `((security)` — unclosed parenthesis
- `OR security` — operator at the start

### Implementation notes

- Parser lives at `app/utils/search_query.py` (recursive descent,
  fully unit-testable, no DB dependency).
- The handler at `api/v1/jobs.py::list_jobs` detects boolean syntax
  via a cheap regex (`is_boolean_query()`) and only invokes the
  parser when triggered. Bare queries take the legacy single-substring
  path with zero overhead.
- Each leaf term still ANY-matches across (title, company, location)
  via three ILIKEs OR'd together — boolean composition operates on
  top of those per-term matches.

---

## Saved filter presets

Khushi's "Problem of Filter Stickness" feedback asked for two things:

- **Filters survive navigation** (already shipped in F34 — JobsPage
  filters sync to URL via `useSearchParams`, so the back button and
  shareable URLs work)
- **Save and recall named filter presets** — Round 72 / F241, this
  doc

### How to use

1. On `/jobs`, set up a filter combination you want to recall later.
   Example: Status = New, Role Cluster = Infra, Geography = Global Remote, Sort = Resume Match.
2. Click the **"Saved (N)"** button next to the search bar (★ icon).
3. In the dropdown, type a name (e.g. "My infra inbox") and click
   **Save**.
4. Next session, click the same button → click your preset name to
   restore the entire filter set in one click.

### Limits

- **Per user**: no platform-wide cap, but per-user UI gets cluttered
  past ~20 presets. Consider naming them descriptively.
- **Name uniqueness**: case-insensitive per user. "Infra" and "infra"
  collide; the second save returns 409 with a useful message.
- **Name length**: 1-100 characters.
- **Filter shape**: free-form JSONB on the backend, so adding a new
  filter axis (e.g. `company_size` when it lands) doesn't need a
  migration — the JobsPage just starts including the new key in the
  `filters` payload it saves.

### What gets saved

Whatever's in the JobsPage's `filters` state at save time:

```ts
{
  search: "(cloud OR kubernetes) AND remote",
  status: "new",
  platform: "",
  geography: "global_remote",
  role_cluster: "infra",
  is_classified: undefined,
  sorts: [{ key: "resume_score", dir: "desc" }],
  // page + page_size are intentionally NOT saved — every preset
  // applies starting from page 1
}
```

### API

- `GET /api/v1/saved-filters` — list your own
- `POST /api/v1/saved-filters` `{name, filters}` — create
- `PATCH /api/v1/saved-filters/{id}` `{name?, filters?}` — update
- `DELETE /api/v1/saved-filters/{id}` — delete (idempotent — 204 even
  if the row didn't exist)

All endpoints are per-user. There's no admin override, no sharing,
no team-wide presets in v1. If sharing becomes useful, it'll be a
separate `shared_filters` table with its own access semantics — not
overloaded onto this one.

### Storage

`saved_filters` table:

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK users | CASCADE on delete (own a user's presets) |
| name | VARCHAR(100) | NOT NULL |
| filters | JSONB | the JobFilters dict |
| created_at, updated_at | TIMESTAMPTZ | |
| `UNIQUE (user_id, lower(name))` index | | case-insensitive uniqueness per user |
| `(user_id, updated_at DESC)` index | | dropdown queries |

---

## Future work

- **Default preset auto-load**: a "set as default" toggle that loads
  the preset on JobsPage mount when the URL has no other filter
  params. Not implemented in v1 — add an `is_default` column when
  needed.
- **Sharable presets**: a separate flow (`?preset=<id>` URL param +
  a `shared_filters` table) for sending a preset to a teammate
  without giving them write access to your saved list.
- **Filter exclusion in preset save**: currently every filter axis
  gets persisted; sometimes a user wants to save only the search
  string and let other filters stay flexible. UI affordance for
  per-axis include/exclude on save.
