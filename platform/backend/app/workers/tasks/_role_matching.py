"""Role matching and geography classification for job titles."""

import re

# ---------------------------------------------------------------------------
# Keyword sets for role cluster detection
# ---------------------------------------------------------------------------

INFRA_KEYWORDS = [
    "devops", "cloud", "infrastructure", "sre", "site reliability",
    "platform engineer", "platform engineering",
    "kubernetes", "k8s", "docker", "terraform", "ansible", "puppet", "chef",
    "aws engineer", "azure engineer", "gcp engineer",
    "linux", "systems engineer", "systems administrator", "sysadmin",
    "network engineer", "network administrator", "network operations",
    "reliability engineer", "release engineer",
    "monitoring", "observability",
    "ci/cd", "cicd", "build engineer", "build and release",
    "finops", "mlops", "dataops", "gitops", "devsecops",
    "cloud architect", "cloud operations", "cloud infrastructure",
    "infrastructure architect", "infrastructure automation",
    "site reliability", "production engineer",
    "datacenter", "data center",
    "openshift", "openstack",
    "containerization", "container orchestration",
    "configuration management", "infrastructure as code",
    "cloud native", "cloudops",
]

SECURITY_KEYWORDS = [
    "security", "devsecops", "soc", "compliance", "grc", "pentest",
    "penetration", "incident response", "red team", "offensive",
    "cyber", "infosec", "information security",
    "vulnerability", "threat", "appsec", "application security",
    "cloud security", "network security",
    "identity", "iam", "access management",
    "data protection", "privacy engineer", "privacy officer",
    "forensic", "malware", "blue team",
    "security architect", "security operations",
    "security compliance", "security analyst",
    "risk analyst", "risk engineer", "risk management",
    "zero trust", "endpoint security",
    "siem", "soar", "edr", "xdr",
    "threat intelligence", "threat detection", "threat hunting",
    "security automation", "secops",
    "cryptography", "encryption",
    "fraud", "anti-fraud",
    "governance", "audit",
]

QA_KEYWORDS = [
    "qa", "quality assurance", "quality engineering",
    "test engineer", "test engineering", "test automation",
    "sdet", "software development engineer in test",
    "quality engineer", "automated testing", "manual testing",
    "selenium", "cypress", "playwright",
    "test lead", "test manager", "qa engineer", "qa analyst",
    "performance testing", "load testing", "regression testing",
    "test framework", "testops", "test architect",
    "functional testing", "integration testing",
    "test infrastructure", "testing tools",
    "appium", "quality management", "qa manager",
    "software tester", "test coordinator",
]

# ---------------------------------------------------------------------------
# Approved role bases (used for title normalization / exact matching)
# ---------------------------------------------------------------------------

INFRA_ROLES = [
    "DevOps Engineer", "Cloud Engineer", "Infrastructure Engineer",
    "Site Reliability Engineer", "Platform Engineer",
    "Cloud Architect", "Infrastructure Architect",
    "Systems Engineer", "Systems Administrator",
    "Network Engineer", "Network Architect",
    "Release Engineer", "Build Engineer",
    "Production Engineer", "Reliability Engineer",
    "Cloud Operations Engineer", "CloudOps Engineer",
    "Kubernetes Engineer", "Container Engineer",
    "Linux Engineer", "Linux Administrator",
    "Automation Engineer",
]

SECURITY_ROLES = [
    "Security Engineer", "DevSecOps Engineer", "Cloud Security Engineer",
    "SOC Analyst", "SOC Engineer", "Compliance Analyst", "GRC Analyst",
    "Compliance Engineer", "Incident Response Engineer",
    "Penetration Tester", "Red Team Engineer",
    "Offensive Security Architect",
    "Security Architect", "Security Analyst",
    "Cybersecurity Engineer", "Cybersecurity Analyst",
    "Information Security Engineer", "Information Security Analyst",
    "Application Security Engineer",
    "Network Security Engineer",
    "Threat Analyst", "Threat Engineer",
    "Vulnerability Engineer", "Vulnerability Analyst",
    "Security Operations Engineer",
    "Privacy Engineer", "Privacy Analyst",
    "Risk Analyst", "Risk Engineer",
    "Identity Engineer", "IAM Engineer",
    "Governance Analyst", "Audit Engineer",
    "Fraud Analyst", "Fraud Engineer",
    "Malware Analyst",
]

QA_ROLES = [
    "QA Engineer", "Quality Assurance Engineer", "Quality Engineer",
    "SDET", "Software Development Engineer in Test",
    "Test Automation Engineer", "Automation Test Engineer",
    "QA Analyst", "Quality Analyst",
    "Test Engineer", "Software Test Engineer",
    "QA Lead", "QA Manager", "Test Lead", "Test Manager",
    "Performance Engineer", "Performance Test Engineer",
    "QA Architect", "Test Architect",
    "Software Tester", "Manual Tester",
]

# ---------------------------------------------------------------------------
# Seniority / level keywords
# ---------------------------------------------------------------------------

LEVEL_KEYWORDS = {
    "principal": "Principal",
    "staff": "Staff",
    "lead": "Lead",
    "senior": "Senior",
    "sr.": "Senior",
    "sr ": "Senior",
    "junior": "Junior",
    "jr.": "Junior",
    "jr ": "Junior",
    "manager": "Manager",
    "architect": "Architect",
    "director": "Director",
    "head of": "Head of",
    "vp": "VP",
}

# ---------------------------------------------------------------------------
# Geography classification — comprehensive signal lists
# ---------------------------------------------------------------------------

# Signals that strongly indicate the role is open globally / worldwide
GLOBAL_REMOTE_SIGNALS = [
    "worldwide", "global remote", "remote - anywhere", "remote (anywhere)",
    "work from anywhere", "fully remote", "remote - global",
    "home based - worldwide", "remote global", "anywhere in the world",
    "location independent", "remote - worldwide", "remote worldwide",
    "distributed", "100% remote",
]

# Patterns for multi-country remote (3+ countries → likely global)
# These are checked separately via regex
MULTI_COUNTRY_PATTERN = re.compile(
    r"remote[,;].*remote[,;].*remote",  # "Remote, US; Remote, UK; Remote, DE"
    re.IGNORECASE,
)

# USA-specific signals
USA_SIGNALS = [
    "us only", "usa only", "united states only", "us-based",
    "remote - us", "remote (us)", "remote - united states",
    "remote us", "usa - remote", "us - remote", "us-remote",
    "remote, united states", "remote, usa", "remote (usa)",
    "united states (remote)", "remote, us",
    "united states - remote", "within canada or united states",
    "north america",
    "u.s. only", "u.s. based", "us based",
    "united states or canada", "us or canada",
    "americas - remote", "americas remote",
]

# UAE-specific signals
UAE_SIGNALS = [
    "uae only", "uae-based", "emirates", "dubai", "abu dhabi",
    "remote - uae", "remote (uae)",
    "united arab emirates", "uae remote", "remote uae",
    "middle east", "gcc",
]

# Country-specific signals that are NOT global (region-locked remote)
# Jobs matching these get no global_remote classification
REGION_LOCKED_SIGNALS = [
    "remote - uk", "remote uk", "uk - remote", "united kingdom (remote)",
    "uk only", "uk based", "uk-based",
    "remote - canada", "remote canada", "canada (remote)", "canada - remote",
    "canada only", "canada based",
    "remote - india", "remote india", "india (remote)",
    "india only", "india based",
    "remote - germany", "remote germany", "germany (remote)",
    "germany only", "germany based",
    "remote - philippines", "remote philippines",
    "remote - mexico", "remote mexico",
    "remote - ireland", "remote ireland", "ireland (remote)",
    "remote - poland", "remote poland",
    "remote - australia", "remote australia", "australia only",
    "remote - brazil", "remote brazil",
    "remote - sweden", "remote sweden",
    "remote - netherlands", "remote netherlands", "netherlands (remote)",
    "remote - switzerland", "remote switzerland",
    "remote - israel", "remote israel",
    "remote - estonia", "remote estonia",
    "remote - singapore", "singapore (remote)",
    "remote - spain", "remote spain", "spain (remote)",
    "remote - france", "remote france", "france (remote)",
    "remote - japan", "remote japan", "japan (remote)",
    "remote - south korea", "remote - korea",
    "remote - nigeria", "remote nigeria",
    "remote - south africa", "remote south africa",
    "remote - colombia", "remote colombia",
    "remote - argentina", "remote argentina",
    "remote - chile", "remote chile",
    "remote - romania", "remote romania",
    "remote - turkey", "remote turkey",
    "remote - portugal", "remote portugal",
    "remote emea", "remote - emea", "home based - emea",
    "emea only", "emea based",
    "remote - europe", "europe only", "eu only",
    "remote - americas", "americas only",
    "remote - apac", "apac only",
    "remote - latam", "latam only", "latin america only",
]


def _normalize(text: str) -> str:
    """Lowercase and collapse whitespace."""
    return re.sub(r"\s+", " ", text.lower().strip())


# Keywords that are short enough to cause substring false positives
# (e.g. "soc" in "associate", "iam" in "claim", "edr" in "Pedro")
# These must match as whole words only.
_WORD_BOUNDARY_KEYWORDS = frozenset([
    "soc", "iam", "grc", "edr", "xdr", "soar", "siem", "audit",
    "qa", "sdet",
])


def _keyword_in_text(keyword: str, text: str) -> bool:
    """Check if a keyword matches in text, using word boundaries for short/ambiguous keywords."""
    if keyword in _WORD_BOUNDARY_KEYWORDS:
        return bool(re.search(r'\b' + re.escape(keyword) + r'\b', text))
    return keyword in text


def load_cluster_config_sync(session) -> dict:
    """Load role cluster config from DB for use in matching.

    Returns {cluster_name: {"keywords": set, "approved_roles": set}}.
    Falls back to empty dict if no active configs found.
    """
    from app.models.role_config import RoleClusterConfig

    rows = session.execute(
        __import__("sqlalchemy").select(RoleClusterConfig).where(
            RoleClusterConfig.is_active.is_(True)
        )
    ).scalars().all()

    config = {}
    for row in rows:
        keywords = {k.strip().lower() for k in (row.keywords or "").split(",") if k.strip()}
        approved_roles = [r.strip() for r in (row.approved_roles or "").split(",") if r.strip()]
        config[row.name] = {
            "keywords": keywords,
            "approved_roles": approved_roles,
        }
    return config


def match_role_from_config(title: str, cluster_config: dict) -> dict:
    """Match a job title using DB-driven cluster config.

    Same logic as match_role() but iterates dynamic config instead of hardcoded lists.
    """
    norm = _normalize(title)
    result = {
        "matched_role": "",
        "role_cluster": "",
        "title_normalized": title.strip(),
        "level": "",
    }

    # Detect seniority level
    for kw, level in LEVEL_KEYWORDS.items():
        if kw in norm:
            result["level"] = level
            break

    # Try exact-ish matching against approved roles from each cluster
    for cluster_name, cfg in cluster_config.items():
        for role in cfg["approved_roles"]:
            if _normalize(role) in norm:
                result["matched_role"] = role
                result["role_cluster"] = cluster_name
                if result["level"]:
                    result["title_normalized"] = f"{result['level']} {role}"
                else:
                    result["title_normalized"] = role
                return result

    # Fallback: keyword-based cluster detection
    for cluster_name, cfg in cluster_config.items():
        for kw in cfg["keywords"]:
            if _keyword_in_text(kw, norm):
                result["role_cluster"] = cluster_name
                result["matched_role"] = title.strip()
                return result

    return result


def match_role_with_config(title: str, cluster_config: dict | None = None) -> dict:
    """Match a role using DB config if available, otherwise hardcoded fallback."""
    if cluster_config:
        return match_role_from_config(title, cluster_config)
    return match_role(title)


def match_role(title: str) -> dict:
    """Match a job title against approved roles.

    Returns dict with:
        matched_role: str   - best matching approved role or empty
        role_cluster: str   - 'infra' | 'security' | ''
        title_normalized: str - cleaned title
        level: str          - detected seniority level
    """
    norm = _normalize(title)
    result = {
        "matched_role": "",
        "role_cluster": "",
        "title_normalized": title.strip(),
        "level": "",
    }

    # Detect seniority level
    for kw, level in LEVEL_KEYWORDS.items():
        if kw in norm:
            result["level"] = level
            break

    # Try exact-ish matching against approved role bases
    for role in INFRA_ROLES:
        if _normalize(role) in norm:
            result["matched_role"] = role
            result["role_cluster"] = "infra"
            if result["level"]:
                result["title_normalized"] = f"{result['level']} {role}"
            else:
                result["title_normalized"] = role
            return result

    for role in SECURITY_ROLES:
        if _normalize(role) in norm:
            result["matched_role"] = role
            result["role_cluster"] = "security"
            if result["level"]:
                result["title_normalized"] = f"{result['level']} {role}"
            else:
                result["title_normalized"] = role
            return result

    for role in QA_ROLES:
        if _normalize(role) in norm:
            result["matched_role"] = role
            result["role_cluster"] = "qa"
            if result["level"]:
                result["title_normalized"] = f"{result['level']} {role}"
            else:
                result["title_normalized"] = role
            return result

    # Fallback: keyword-based cluster detection
    for kw in INFRA_KEYWORDS:
        if _keyword_in_text(kw, norm):
            result["role_cluster"] = "infra"
            result["matched_role"] = title.strip()
            return result

    for kw in SECURITY_KEYWORDS:
        if _keyword_in_text(kw, norm):
            result["role_cluster"] = "security"
            result["matched_role"] = title.strip()
            return result

    for kw in QA_KEYWORDS:
        if _keyword_in_text(kw, norm):
            result["role_cluster"] = "qa"
            result["matched_role"] = title.strip()
            return result

    return result


def classify_geography(location_raw: str, remote_scope: str) -> str:
    """Classify a job into a geography bucket based on location and remote scope text.

    Returns one of: 'global_remote', 'usa_only', 'uae_only', or '' (unknown).
    """
    combined = _normalize(f"{location_raw} {remote_scope}")

    # Check region-locked FIRST — these are NOT global even though they say "remote"
    for signal in REGION_LOCKED_SIGNALS:
        if signal in combined:
            return ""  # Region-locked, not classifiable into our buckets

    # Check global remote signals
    for signal in GLOBAL_REMOTE_SIGNALS:
        if signal in combined:
            return "global_remote"

    # Multi-country postings (3+ "remote" mentions) → likely global
    if MULTI_COUNTRY_PATTERN.search(combined):
        return "global_remote"

    # USA signals
    for signal in USA_SIGNALS:
        if signal in combined:
            return "usa_only"

    # UAE signals
    for signal in UAE_SIGNALS:
        if signal in combined:
            return "uae_only"

    # Heuristic: bare "remote" with NO country/region → treat as potentially global
    # This catches "Remote" with remote_scope="remote" but no location qualifier
    if remote_scope and "remote" in remote_scope.lower():
        loc = _normalize(location_raw)
        # If location is just "Remote" or empty, it's likely global
        if not loc or loc == "remote" or loc == "fully remote" or loc == "remote, remote":
            return "global_remote"

    # Additional heuristic: location_raw itself is a global-sounding phrase
    loc_lower = _normalize(location_raw)
    if loc_lower in (
        "anywhere", "worldwide", "global", "remote",
        "anywhere in the world", "work from anywhere",
        "fully remote", "100% remote", "remote - anywhere",
    ):
        return "global_remote"

    # Location contains "united states" or "usa" without "remote" prefix — likely USA
    if any(sig in loc_lower for sig in ("united states", "usa", "u.s.")):
        return "usa_only"

    return ""
