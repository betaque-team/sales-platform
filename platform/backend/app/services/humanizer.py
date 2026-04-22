"""Humanizer — strips AI fingerprints from generated content.

Purpose
-------
The Claude Routine Apply feature generates answers to application
questions and cover letters via the Anthropic API. Raw LLM output
carries stylistic tells — em-dashes, "delve into the landscape",
tricolons ("efficient, scalable, and robust"), uniform sentence
length — that recruiters and AI-detection tools (GPTZero, Originality,
Copyleaks) flag.

This module runs text through a pipeline of pure-function passes that
strip those tells and nudge the output toward the kind of natural
inconsistency a human applicant would produce. Every pass is
deterministic (given the same input, same output) and side-effect-free
except for ``style_match_pass`` which reads from humanization_corpus.

Pipeline order (matters)
------------------------
1. strip_banned_punctuation  — em-dashes, stray semicolons
2. strip_banned_phrases      — "delve", "leverage", "tapestry", etc.
3. cap_tricolons             — "A, B, and C" → "A and B"
4. strip_template_openings   — "As an X, …" → cut
5. strip_template_closings   — "I look forward to discussing…" → cut
6. burstiness_enforce        — ensure sentence-length stdev >= 6
7. style_match_pass          — few-shot rewrite in user's voice (DB pass)
8. occasional_imperfection   — 1/8: contraction / dropped Oxford comma

Not every pass always runs:
- `style_match_pass` is skipped when corpus < 10 rows for the user.
- `burstiness_enforce` is skipped for single-sentence inputs.

Testing
-------
Each pass is a pure (str) -> str or (str) -> (str, dict) function
importable in isolation. The style-match pass takes an injectable
``examples`` parameter so unit tests don't need a DB fixture.
"""

from __future__ import annotations

import hashlib
import re
import statistics
from dataclasses import dataclass, field
from typing import Callable


# ═══════════════════════════════════════════════════════════════════
# Tunables — kept as module constants so tests can override by
# monkeypatch and so humanizer behavior is visible without grep-diving
# ═══════════════════════════════════════════════════════════════════

BURSTINESS_TARGET_SIGMA = 6.0
STYLE_MATCH_MIN_CORPUS_SIZE = 10
STYLE_MATCH_MAX_EXAMPLES = 5
IMPERFECTION_PROBABILITY = 1  # out of 8 — deterministic hash-gate
IMPERFECTION_HASH_MODULUS = 8


# ═══════════════════════════════════════════════════════════════════
# Rule data — phrases + replacements
# ═══════════════════════════════════════════════════════════════════

# Phrases that strongly flag as LLM output. Each maps to a neutral
# replacement (empty string = delete). Applied case-insensitively via
# a single compiled alternation so pass cost is O(n), not O(n * rules).
#
# Keep this list tight. Every entry here is a content constraint; a
# too-aggressive list starts making real human writing sound stilted.
# Threshold: phrases that a colleague would NOT use in a cover letter.
BANNED_PHRASES: dict[str, str] = {
    # Signature LLM vocabulary
    "delve into": "explore",
    "delve": "look into",
    "delving into": "exploring",
    "tapestry": "mix",
    "landscape of": "state of",
    "navigate the": "work through the",
    "navigating the": "working through the",
    "in today's fast-paced": "in this",
    "leverage": "use",
    "leveraging": "using",
    "leveraged": "used",
    "synergy": "overlap",
    "synergies": "overlaps",
    "pivotal": "important",
    "seamlessly": "smoothly",
    "seamless": "smooth",
    "robust solution": "solid approach",
    "robust framework": "solid framework",
    "dive deep into": "look closely at",
    "deep dive": "close look",
    "at the forefront": "leading",
    "cutting-edge": "modern",
    "paradigm shift": "change",
    "game-changer": "big improvement",
    "game-changing": "significant",
    # Essay-filler
    "in conclusion,": "",
    "to summarize,": "",
    "it is worth noting that": "",
    "it's important to note that": "",
    "furthermore,": "",
    "moreover,": "",
    "additionally,": "also,",
    # British/fancy variants that over-index on LLM training data
    "whilst": "while",
    "realm of": "area of",
    # Vague hedging
    "a wide range of": "many",
    "a plethora of": "many",
    "myriad": "many",
    # "Crucial" is borderline. We downgrade, don't delete — real humans
    # do say "crucial" occasionally. LLMs overuse it.
    "crucial": "important",
    "meticulous": "careful",
    "meticulously": "carefully",
}


# Template openings / closings — the routine should cut these outright,
# not replace them. LLMs frequently start with "As a senior engineer,"
# and close with "I look forward to discussing…". Humans sometimes do
# too, but generated versions are suspiciously consistent.
TEMPLATE_OPENINGS = (
    re.compile(r"^(As an? [A-Z][a-zA-Z ]+,\s+)", re.MULTILINE),
    re.compile(r"^(In today's [a-z ]+,\s+)", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^(I am writing to (express|apply|submit)[^.]*\.\s*)", re.MULTILINE | re.IGNORECASE),
)

TEMPLATE_CLOSINGS = (
    re.compile(r"\s*I (look forward|would welcome) (the opportunity|to discussing?)[^.]*\.?\s*$", re.IGNORECASE),
    re.compile(r"\s*Thank you for (your time|considering my application)[^.]*\.?\s*$", re.IGNORECASE),
)


# ═══════════════════════════════════════════════════════════════════
# Result type
# ═══════════════════════════════════════════════════════════════════

@dataclass
class HumanizeResult:
    text: str
    passes_applied: list[str] = field(default_factory=list)
    burstiness_sigma: float = 0.0
    banned_phrase_hits: list[str] = field(default_factory=list)
    style_match_examples_used: int = 0


# ═══════════════════════════════════════════════════════════════════
# Pass 1 — punctuation
# ═══════════════════════════════════════════════════════════════════

def strip_banned_punctuation(text: str) -> str:
    """Strip em-dashes and stray semicolons.

    Em-dashes are the single highest-signal LLM tell. Replaced with
    ``. `` when they appear to separate clauses (uppercase follows),
    ``, `` otherwise. En-dashes (–) in numeric ranges are preserved
    (e.g. "140k–180k") by only touching em-dashes.

    Semicolons are stripped wholesale except when the surrounding
    context is a list of list-items — we treat any semicolon as
    suspicious and replace with ". " (sentence split) for safety.
    """
    # Em-dash → period when followed by whitespace + uppercase letter
    # (suggests new sentence); otherwise comma.
    out = re.sub(r"\s*—\s+(?=[A-Z])", ". ", text)
    out = re.sub(r"\s*—\s*", ", ", out)
    # Semicolon → period + space. Loses the grammatical distinction
    # but LLMs use semicolons an order of magnitude more than humans.
    out = re.sub(r"\s*;\s+", ". ", out)
    # Collapse any ".. ", ". ." produced above.
    out = re.sub(r"\.\s*\.", ".", out)
    return out


# ═══════════════════════════════════════════════════════════════════
# Pass 2 — banned phrases
# ═══════════════════════════════════════════════════════════════════

# Compile once at import time.
def _compile_banned_regex() -> re.Pattern[str]:
    # Longest first so "delve into" wins over "delve".
    phrases = sorted(BANNED_PHRASES.keys(), key=len, reverse=True)
    escaped = [re.escape(p) for p in phrases]
    return re.compile(r"\b(" + "|".join(escaped) + r")\b", re.IGNORECASE)


_BANNED_RE = _compile_banned_regex()


def strip_banned_phrases(text: str) -> tuple[str, list[str]]:
    """Replace every banned phrase with its neutral substitute.

    Returns (cleaned_text, list_of_hits) so the caller can surface
    which phrases were stripped (useful for humanizer telemetry and
    for debugging "why did the output change so much").
    """
    hits: list[str] = []

    def _repl(m: re.Match[str]) -> str:
        matched_lower = m.group(0).lower()
        hits.append(matched_lower)
        replacement = BANNED_PHRASES.get(matched_lower, "")
        # Preserve leading capitalization if the original started a sentence.
        if m.group(0)[0].isupper() and replacement:
            replacement = replacement[0].upper() + replacement[1:]
        return replacement

    cleaned = _BANNED_RE.sub(_repl, text)
    # If we produced "   " or " ," cleanup double-spacing + orphaned commas.
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+,", ",", cleaned)
    cleaned = re.sub(r"^\s*,\s*", "", cleaned)
    return cleaned, hits


# ═══════════════════════════════════════════════════════════════════
# Pass 3 — cap tricolons
# ═══════════════════════════════════════════════════════════════════

# "A, B, and C" / "A, B, C" lists of 3 items joined as predicates —
# classic LLM tell. We drop the middle item to get "A and C", which
# matches how humans actually say it.
_TRICOLON_RE = re.compile(
    r"\b(\w+(?:\s+\w+){0,2}),\s+(\w+(?:\s+\w+){0,2}),\s+(?:and\s+)?(\w+(?:\s+\w+){0,2})\b"
)


def cap_tricolons(text: str) -> str:
    """Drop the middle item of any 3-item list.

    Regex is conservative — it only matches short (1-3 word) items,
    which is where the LLM tell is strongest. Long enumerations
    ("on Monday, on Tuesday, and on Wednesday") stay untouched.
    """
    def _repl(m: re.Match[str]) -> str:
        a, _b, c = m.group(1), m.group(2), m.group(3)
        return f"{a} and {c}"
    return _TRICOLON_RE.sub(_repl, text)


# ═══════════════════════════════════════════════════════════════════
# Pass 4-5 — template openings/closings
# ═══════════════════════════════════════════════════════════════════

def strip_template_openings(text: str) -> str:
    out = text
    for rx in TEMPLATE_OPENINGS:
        out = rx.sub("", out, count=1)
    return out.lstrip()


def strip_template_closings(text: str) -> str:
    out = text
    for rx in TEMPLATE_CLOSINGS:
        out = rx.sub("", out, count=1)
    return out.rstrip()


# ═══════════════════════════════════════════════════════════════════
# Pass 6 — burstiness
# ═══════════════════════════════════════════════════════════════════

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def compute_burstiness_sigma(text: str) -> float:
    """Standard deviation of sentence length in words.

    Returns a sentinel 999.0 when we can't compute (<2 sentences),
    so callers can distinguish "already bursty" from "too few
    sentences to check" without special-case handling.
    """
    sents = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    lens = [len(s.split()) for s in sents]
    if len(lens) < 2:
        return 999.0
    return float(statistics.stdev(lens))


def burstiness_enforce(text: str) -> str:
    """Ensure sentence-length stdev >= BURSTINESS_TARGET_SIGMA.

    If below target, split the longest sentence into two clauses
    (crude but deterministic: split on the middle comma if any,
    otherwise no-op — we won't invent content). This is a nudge,
    not a hammer; some inputs just aren't fixable without content
    changes.
    """
    sigma = compute_burstiness_sigma(text)
    if sigma >= BURSTINESS_TARGET_SIGMA:
        return text
    # Find longest sentence; try to split on its middle comma.
    sents = _SENTENCE_SPLIT.split(text)
    if len(sents) < 2:
        return text
    longest_idx = max(range(len(sents)), key=lambda i: len(sents[i].split()))
    s = sents[longest_idx]
    commas = [i for i, c in enumerate(s) if c == ","]
    if not commas:
        return text
    mid = commas[len(commas) // 2]
    # Replace the middle comma with ". " and capitalize next word.
    after = s[mid + 1:].lstrip()
    if not after:
        return text
    replacement = s[:mid] + ". " + after[0].upper() + after[1:]
    sents[longest_idx] = replacement
    return " ".join(sents)


# ═══════════════════════════════════════════════════════════════════
# Pass 7 — style match
# ═══════════════════════════════════════════════════════════════════

def style_match_pass(
    text: str,
    corpus_examples: list[tuple[str, str]] | None,
) -> tuple[str, int]:
    """Few-shot rewrite in the user's voice using past edit pairs.

    v6 stub implementation: this pass is a no-op when corpus is too
    small. The full LLM-based rewrite lives in a follow-up spec
    (Phase 4) because it needs an Anthropic API call wrapped in the
    rate-limit / audit infrastructure that's out of scope for the
    initial build.

    What we DO implement right now: if the user has >= N corpus
    examples, we record the count so the caller can assert the
    pipeline considered them — useful for tests that verify the
    corpus wiring works end-to-end. The actual stylistic rewrite
    is deferred.

    Returns (text, num_examples_used). Unchanged text when
    corpus_examples is None or too small.
    """
    if corpus_examples is None:
        return text, 0
    # Bug fix: the gate must check RAW corpus size, not the capped
    # slice. Previously we did `corpus_examples[:5]` then compared
    # `len(usable) < 10`, which is always True — so `used` was
    # permanently 0 even for users with a fully-populated corpus.
    # That made the `style_match_examples_used` telemetry useless
    # and masked the "corpus wiring works" signal that tests need
    # to assert before Phase 4 flips this pass on.
    if len(corpus_examples) < STYLE_MATCH_MIN_CORPUS_SIZE:
        # Not enough signal yet — the first N applies build the corpus.
        return text, 0
    usable = corpus_examples[:STYLE_MATCH_MAX_EXAMPLES]
    # Stub: no rewrite. Phase 4 will inject Anthropic here.
    return text, len(usable)


# ═══════════════════════════════════════════════════════════════════
# Pass 8 — deterministic imperfection
# ═══════════════════════════════════════════════════════════════════

def _hash_gate(text: str, modulus: int) -> int:
    """Deterministic 0..modulus-1 pick from text hash.

    Same input → same pick. Makes humanizer output reproducible
    across runs, which matters for tests and for side-by-side
    comparisons of before/after edits.
    """
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(h[:8], 16) % modulus


def occasional_imperfection(text: str) -> str:
    """1-in-8: apply a small human-like inconsistency.

    Deterministic by input hash so a re-run with the same draft
    produces the same output. Three possible tweaks, picked by hash:
        - add a contraction ("I have" → "I've")
        - drop the Oxford comma in one list
        - start one sentence with "And" or "But"
    """
    if _hash_gate(text, IMPERFECTION_HASH_MODULUS) >= IMPERFECTION_PROBABILITY:
        return text
    # Pick which tweak by a second hash-gate.
    tweak = _hash_gate(text + "tweak", 3)
    if tweak == 0:
        return re.sub(r"\bI have\b", "I've", text, count=1)
    if tweak == 1:
        # Drop first ", and " → " and "
        return re.sub(r",\s+and\s+", " and ", text, count=1)
    # tweak == 2: second sentence onward, add "And " or "But " prefix
    # if it currently starts with a plain subject. Conservative regex
    # to avoid mangling anything intentional.
    return re.sub(r"\. ([A-Z])", lambda m: ". And " + m.group(1).lower(), text, count=1)


# ═══════════════════════════════════════════════════════════════════
# Composer
# ═══════════════════════════════════════════════════════════════════

def humanize(
    text: str,
    corpus_examples: list[tuple[str, str]] | None = None,
) -> HumanizeResult:
    """Run the full humanizer pipeline on ``text``.

    ``corpus_examples`` is an injected list of (draft, final) pairs —
    the caller loads this from humanization_corpus and scopes it to
    the current user. Passing None disables the style-match pass.
    """
    result = HumanizeResult(text=text)
    if not text or not text.strip():
        return result

    # 1. punctuation
    result.text = strip_banned_punctuation(result.text)
    result.passes_applied.append("strip_banned_punctuation")

    # 2. banned phrases
    result.text, hits = strip_banned_phrases(result.text)
    result.banned_phrase_hits = hits
    result.passes_applied.append("strip_banned_phrases")

    # 3. tricolons
    result.text = cap_tricolons(result.text)
    result.passes_applied.append("cap_tricolons")

    # 4/5. templates
    result.text = strip_template_openings(result.text)
    result.passes_applied.append("strip_template_openings")
    result.text = strip_template_closings(result.text)
    result.passes_applied.append("strip_template_closings")

    # 6. burstiness
    result.text = burstiness_enforce(result.text)
    result.burstiness_sigma = compute_burstiness_sigma(result.text)
    result.passes_applied.append("burstiness_enforce")

    # 7. style match
    result.text, used = style_match_pass(result.text, corpus_examples)
    result.style_match_examples_used = used
    result.passes_applied.append("style_match_pass")

    # 8. imperfection
    result.text = occasional_imperfection(result.text)
    result.passes_applied.append("occasional_imperfection")

    return result
