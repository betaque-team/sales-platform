"""ATS resume scoring engine — keyword matching, role alignment, format checks."""

import re
from typing import Any

from app.workers.tasks._role_matching import (
    INFRA_KEYWORDS, SECURITY_KEYWORDS, QA_KEYWORDS,
    INFRA_ROLES, SECURITY_ROLES, QA_ROLES,
)

# ---------------------------------------------------------------------------
# Tech keyword categories for matching resume ↔ job
# ---------------------------------------------------------------------------

TECH_CATEGORIES = {
    "cloud_platforms": [
        "aws", "azure", "gcp", "google cloud", "alibaba cloud", "oracle cloud",
        "digitalocean", "linode", "vultr",
    ],
    "infrastructure_as_code": [
        "terraform", "pulumi", "cloudformation", "ansible", "chef", "puppet",
        "salt", "saltstack", "packer", "vagrant",
    ],
    "containers_orchestration": [
        "docker", "kubernetes", "k8s", "eks", "ecs", "gke", "aks",
        "helm", "istio", "envoy", "podman", "containerd",
        "openshift", "rancher", "nomad",
    ],
    "cicd": [
        "jenkins", "github actions", "gitlab ci", "circleci", "argocd",
        "travis ci", "teamcity", "bamboo", "drone ci", "tekton",
        "spinnaker", "flux", "concourse",
    ],
    "monitoring_observability": [
        "datadog", "prometheus", "grafana", "splunk", "elk",
        "elasticsearch", "logstash", "kibana", "new relic", "newrelic",
        "pagerduty", "opsgenie", "jaeger", "zipkin", "opentelemetry",
        "nagios", "zabbix", "cloudwatch", "stackdriver",
    ],
    "security_tools": [
        "siem", "soar", "burp suite", "nessus", "qualys", "tenable",
        "crowdstrike", "sentinelone", "snyk", "veracode", "checkmarx",
        "sonarqube", "trivy", "aqua", "prisma cloud", "wiz",
        "hashicorp vault", "vault", "opa", "falco",
    ],
    "compliance_frameworks": [
        "nist", "iso 27001", "soc 2", "soc2", "gdpr", "hipaa", "pci dss",
        "pci-dss", "fedramp", "cis benchmark", "owasp", "cobit",
        "ccpa", "sox", "csa star",
    ],
    "networking": [
        "vpc", "dns", "cdn", "load balancer", "nginx", "haproxy",
        "cloudflare", "route 53", "vpn", "wireguard", "ipsec",
        "tcp/ip", "tcp", "http", "tls", "ssl",
    ],
    "languages": [
        "python", "go", "golang", "bash", "shell scripting", "powershell",
        "typescript", "javascript", "rust", "java", "ruby", "perl",
        "c++", "c#",
    ],
    "databases": [
        "postgresql", "postgres", "mysql", "redis", "mongodb", "dynamodb",
        "elasticsearch", "cassandra", "cockroachdb", "mariadb",
        "sqlite", "memcached", "neo4j",
    ],
    "devops_practices": [
        "ci/cd", "infrastructure as code", "iac", "gitops", "devsecops",
        "site reliability", "sre", "devops", "agile", "scrum",
        "incident management", "runbook", "postmortem", "chaos engineering",
    ],
    "qa_testing": [
        "selenium", "cypress", "playwright", "appium", "webdriver",
        "jest", "pytest", "testng", "junit", "mocha", "jasmine",
        "robot framework", "cucumber", "behave", "gherkin",
        "jmeter", "gatling", "locust", "k6", "artillery",
        "postman", "newman", "rest assured", "karate",
        "browserstack", "sauce labs", "lambdatest",
        "test automation", "quality assurance", "sdet",
        "regression testing", "performance testing", "load testing",
        "api testing", "e2e testing", "test plan", "test case",
    ],
}

# Flatten all keywords for quick lookup
ALL_TECH_KEYWORDS: set[str] = set()
for keywords in TECH_CATEGORIES.values():
    ALL_TECH_KEYWORDS.update(keywords)

# Resume section keywords
RESUME_SECTIONS = [
    "experience", "work experience", "professional experience",
    "skills", "technical skills", "education", "certifications",
    "projects", "summary", "objective", "achievements",
]


# Regression finding 95: previously the word-boundary threshold was
# `len(keyword) <= 2`, so 3-4 char tech acronyms (`aws`, `gcp`, `sre`,
# `dns`, `cdn`, `vpc`, `tcp`, `tls`, `ssl`, `elk`, `iac`, `eks`,
# `ecs`, `gke`, `aks`, `sox`, `iso`, `sap`, `helm`, `java`, `ruby`,
# `perl`, `bash`, `nist`) fell into the substring branch and matched
# inside unrelated words — "aws" in "laws", "sre" in "presented",
# "elk" in "welkin", "java" in "javascript". Bumped to 4 so every
# short acronym gets word-boundary semantics; anything longer keeps
# the faster `in` check. Multi-word keywords like `"tcp/ip"` are
# 6 chars so unaffected, and the `\b` token matches between word /
# non-word chars (so `\btcp\b` still matches inside `"tcp/ip"`).
_ATS_WORD_BOUNDARY_MAX_LEN = 4


def _extract_keywords_from_text(text: str) -> set[str]:
    """Extract matching tech keywords from text."""
    text_lower = text.lower()
    found = set()
    for keyword in ALL_TECH_KEYWORDS:
        if len(keyword) <= _ATS_WORD_BOUNDARY_MAX_LEN:
            if re.search(r'\b' + re.escape(keyword) + r'\b', text_lower):
                found.add(keyword)
        else:
            if keyword in text_lower:
                found.add(keyword)
    return found


def _extract_job_keywords(job_title: str, role_cluster: str, matched_role: str, description_text: str = "") -> set[str]:
    """Extract expected keywords from a job posting.

    Regression finding 94: the QA cluster previously had no baseline
    backfill, so a QA job with an empty description produced an empty
    expected-keyword set — which then hit the `compute_keyword_score`
    short-circuit and awarded a free 50.0. Every known relevant
    cluster now seeds at least a handful of domain keywords, so the
    only remaining path to empty `job_keywords` is "unclassified job
    with empty description AND empty title" — which is correctly
    scored as zero in `compute_keyword_score`.
    """
    keywords = set()

    # From job description text
    if description_text:
        keywords.update(_extract_keywords_from_text(description_text))

    # From role cluster — add core keywords for that domain.
    #
    # Regression finding 165: the baselines used to seed generic domain
    # terms that are NOT present in `ALL_TECH_KEYWORDS` — `"cloud"` and
    # `"infrastructure"` for infra, `"security"` and `"compliance"` for
    # security. Because `_extract_keywords_from_text()` only scans for
    # members of `ALL_TECH_KEYWORDS`, those four tokens could never be
    # matched from a resume, so every infra/security job got 2 unmatchable
    # "missing" keywords baked in. Net effect: max achievable keyword
    # score on infra/security was ~78/83 (not 100), and the suggestions
    # panel endlessly recommended "add 'cloud' to your resume" — which
    # then still wouldn't match because the extractor doesn't look for
    # bare `"cloud"`. QA baselines were already phantom-free (all members
    # of `qa_testing`), so QA consistently out-scored infra/security in
    # the cross-resume calibration that surfaced the bug.
    #
    # Fix: drop the phantoms. The cluster's real top-3 tools still
    # anchor each baseline, so an empty-description job still has a
    # non-empty keyword set (i.e. the F94 short-circuit path stays
    # intact), but the set only contains tokens the extractor can
    # actually find in resumes. `"ci/cd"` and `"devops"` stay because
    # both live in the `devops_practices` category — they are real,
    # matchable keywords.
    if role_cluster == "infra":
        keywords.update(["devops", "ci/cd"])
        for cat in ["cloud_platforms", "containers_orchestration", "cicd", "infrastructure_as_code"]:
            # Add top 3 from each category as baseline expectations
            keywords.update(TECH_CATEGORIES[cat][:3])
    elif role_cluster == "security":
        for cat in ["security_tools", "compliance_frameworks"]:
            keywords.update(TECH_CATEGORIES[cat][:3])
    elif role_cluster == "qa":
        # Regression finding 94: add the missing QA backfill so QA
        # postings with empty descriptions don't slip through to the
        # "no job_keywords → free 50.0" short-circuit. Selects the
        # most universal QA tools/practices as minimum expectations.
        keywords.update(["quality assurance", "test automation", "sdet"])
        keywords.update(TECH_CATEGORIES["qa_testing"][:6])

    # From title keywords
    title_keywords = _extract_keywords_from_text(job_title)
    keywords.update(title_keywords)

    return keywords


def compute_keyword_score(resume_keywords: set[str], job_keywords: set[str]) -> tuple[float, list[str], list[str]]:
    """Compute keyword overlap score.

    Returns (score 0-100, matched_list, missing_list).

    Regression finding 94: the old empty-job_keywords short-circuit
    returned `(50.0, resume_keywords[:20], [])` — which gave every
    job with an empty description a free 25 points on the weighted
    overall (50% keyword weight × 50 = 25) AND falsely labeled up to
    20 resume tokens as "matched". A resume scored against an
    empty-JD job looked better than one scored against a
    well-documented JD, since missing keywords penalise the latter.
    Now we honestly report zero when the job offered nothing to
    compare against, with both lists empty so the UI won't display
    "matched: aws, docker, …" for tokens that were never required.
    """
    if not job_keywords:
        return 0.0, [], []

    matched = resume_keywords & job_keywords
    missing = job_keywords - resume_keywords

    # Score is percentage of job keywords found in resume
    score = (len(matched) / len(job_keywords)) * 100 if job_keywords else 0
    return min(score, 100.0), sorted(matched), sorted(missing)


# Regression finding 166: role alignment used to be `matches / len(role_keywords) * 100`
# over the FULL INFRA/SECURITY/QA keyword+role lists (often 40-80 entries) PLUS the
# resume was also being compared implicitly to every TECH_CATEGORIES keyword via the
# keyword score — so a DevOps candidate with 18 strong matches (aws, kubernetes,
# terraform, …) could only score ~39/100 role alignment because the denominator was
# unreachable. The fraction was effectively "% of ALL role vocabulary you recognise"
# rather than "are you qualified for this role?". Combined with the 30% role weight
# that capped the ceiling around 82 even for a perfect resume.
#
# Fix: use a saturating threshold — anyone matching `_ROLE_ALIGNMENT_THRESHOLD`
# role-relevant tokens is treated as fully aligned (100), and linear below that.
# That gives a strong DevOps/Security/QA candidate a realistic chance at 100 role
# alignment while still rewarding depth (more keywords → higher score, up to the cap).
# The +20 bonus for exact matched-role appearance is preserved.
_ROLE_ALIGNMENT_THRESHOLD = 12


def compute_role_alignment(resume_text: str, role_cluster: str, matched_role: str) -> float:
    """Score how well resume aligns with the job's role cluster. Returns 0-100."""
    text_lower = resume_text.lower()

    if role_cluster == "infra":
        role_keywords = INFRA_KEYWORDS + [r.lower() for r in INFRA_ROLES]
    elif role_cluster == "security":
        role_keywords = SECURITY_KEYWORDS + [r.lower() for r in SECURITY_ROLES]
    elif role_cluster == "qa":
        role_keywords = QA_KEYWORDS + [r.lower() for r in QA_ROLES]
    else:
        return 50.0  # neutral for unclassified

    matches = sum(1 for kw in role_keywords if kw in text_lower)

    # Saturating linear score: 0 matches → 0, threshold matches → 100.
    # Honest candidates with 12+ role-relevant tokens max out at 100 instead
    # of being capped at 40-50 by the old full-vocabulary denominator.
    score = min((matches / _ROLE_ALIGNMENT_THRESHOLD) * 100, 100.0)

    # Bonus if the exact matched role appears in resume
    if matched_role and matched_role.lower() in text_lower:
        score = min(score + 20, 100.0)

    return score


def compute_format_score(resume_text: str) -> float:
    """Score resume format/completeness signals. Returns 0-100."""
    score = 0.0
    text_lower = resume_text.lower()

    # Check for standard sections
    sections_found = sum(1 for s in RESUME_SECTIONS if s in text_lower)
    score += min(sections_found * 15, 45)

    # Check for contact info
    if re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', resume_text):
        score += 15  # email found
    if re.search(r'[\+]?\d[\d\s\-().]{8,}', resume_text):
        score += 10  # phone found

    # Check for quantifiable achievements
    if re.search(r'\d+%|\d+x|reduced|increased|improved|optimized|scaled', text_lower):
        score += 15

    # Word count check (300-2000 words is ideal for ATS)
    word_count = len(resume_text.split())
    if 300 <= word_count <= 2000:
        score += 15
    elif word_count > 100:
        score += 5

    return min(score, 100.0)


def generate_suggestions(
    missing_keywords: list[str],
    role_alignment: float,
    format_score: float,
    job_title: str,
    role_cluster: str,
) -> list[str]:
    """Generate actionable suggestions to improve ATS score."""
    suggestions = []

    # Keyword suggestions
    if missing_keywords:
        top_missing = missing_keywords[:8]
        suggestions.append(
            f"Add these keywords to your resume: {', '.join(top_missing)}. "
            f"These are commonly expected for {job_title} roles."
        )

    # Role alignment suggestions
    if role_alignment < 50:
        if role_cluster == "infra":
            suggestions.append(
                "Strengthen your DevOps/Cloud/SRE experience section. "
                "Mention specific cloud platforms (AWS, GCP, Azure), "
                "IaC tools (Terraform, Ansible), and container orchestration (Kubernetes, Docker)."
            )
        elif role_cluster == "security":
            suggestions.append(
                "Highlight security-specific experience. Include security tools, "
                "compliance frameworks (SOC 2, ISO 27001, NIST), and security practices."
            )

    # Format suggestions
    if format_score < 50:
        suggestions.append(
            "Improve your resume structure: ensure you have clear sections for "
            "Experience, Skills, Education, and Certifications."
        )
    if format_score < 70:
        suggestions.append(
            "Add quantifiable achievements (e.g., 'Reduced deployment time by 40%', "
            "'Managed 500+ servers')."
        )

    if not suggestions:
        suggestions.append("Your resume is well-optimized for this position!")

    return suggestions


def compute_ats_score(
    resume_text: str,
    job_title: str,
    matched_role: str,
    role_cluster: str,
    description_text: str = "",
) -> dict[str, Any]:
    """Compute full ATS score for a resume against a job.

    Returns dict with overall_score, keyword_score, role_match_score,
    format_score, matched_keywords, missing_keywords, suggestions.
    """
    # Extract keywords
    resume_keywords = _extract_keywords_from_text(resume_text)
    job_keywords = _extract_job_keywords(job_title, role_cluster, matched_role, description_text)

    # Compute scores
    keyword_score, matched, missing = compute_keyword_score(resume_keywords, job_keywords)
    role_score = compute_role_alignment(resume_text, role_cluster, matched_role)

    # Technical depth guard: penalize role alignment for resumes with very few tech keywords
    tech_depth = len(resume_keywords)
    if tech_depth < 3:
        role_score = min(role_score, 15.0)   # almost no tech keywords — not a technical resume
    elif tech_depth < 6:
        role_score = min(role_score, 35.0)   # some tech exposure but limited
    elif tech_depth < 10:
        role_score = min(role_score * 0.75, 100.0)  # moderate tech background

    format_score = compute_format_score(resume_text)

    # Weighted overall: 50% keywords, 30% role alignment, 20% format
    overall = (keyword_score * 0.50) + (role_score * 0.30) + (format_score * 0.20)

    suggestions = generate_suggestions(missing, role_score, format_score, job_title, role_cluster)

    return {
        "overall_score": round(overall, 1),
        "keyword_score": round(keyword_score, 1),
        "role_match_score": round(role_score, 1),
        "format_score": round(format_score, 1),
        "matched_keywords": matched,
        "missing_keywords": missing,
        "suggestions": suggestions,
    }
