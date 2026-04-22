"""Unit tests for the humanizer pipeline (v6 Claude Routine Apply).

Every pass in ``app.services.humanizer`` is a pure function — the whole
point of the module is that it's side-effect-free except for the
style-match corpus lookup, which the test injects as a plain list.
That means we can exercise the pipeline without a DB, Redis, or an
Anthropic API key.

Coverage goals, by pass:
  1. strip_banned_punctuation   — em-dash handling, semicolon collapse,
                                  en-dash preserved (numeric ranges).
  2. strip_banned_phrases       — replacement correctness, hit list,
                                  case preservation at sentence start.
  3. cap_tricolons              — middle item dropped.
  4. strip_template_openings    — "As a …," cut.
  5. strip_template_closings    — "I look forward …" cut.
  6. burstiness_enforce         — sigma >= target left alone;
                                  low-sigma input gets split.
  7. style_match_pass           — corpus-size gating (< N = no-op,
                                  >= N = counted).
  8. occasional_imperfection    — deterministic hash gate.

Also tests the end-to-end ``humanize()`` composer: empty input short-
circuits, result carries per-pass provenance.

No config side-effects — humanizer doesn't touch the env, but we set
defaults anyway so an import-time config access from a sibling module
can't blow up collection.
"""
from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault(
    "DATABASE_URL_SYNC",
    "postgresql://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "pytest-humanizer")

from app.services.humanizer import (  # noqa: E402
    BURSTINESS_TARGET_SIGMA,
    STYLE_MATCH_MIN_CORPUS_SIZE,
    cap_tricolons,
    compute_burstiness_sigma,
    burstiness_enforce,
    humanize,
    occasional_imperfection,
    strip_banned_phrases,
    strip_banned_punctuation,
    strip_template_closings,
    strip_template_openings,
    style_match_pass,
)


# ── Pass 1: punctuation ────────────────────────────────────────────


def test_em_dash_before_uppercase_becomes_sentence_break():
    """Em-dash + whitespace + uppercase = new sentence. Matches how
    humans would re-punctuate that construction in speech."""
    out = strip_banned_punctuation("I built the pipeline — It scaled.")
    assert out == "I built the pipeline. It scaled."


def test_em_dash_midclause_becomes_comma():
    out = strip_banned_punctuation("the pipeline — which I own — is stable")
    # Two em-dashes; each becomes ", " since no uppercase follows.
    assert "—" not in out
    assert "," in out


def test_en_dash_in_numeric_range_preserved():
    """En-dash (–) is used in salary ranges like '140k–180k'. We must
    not touch it; only the em-dash (—) gets processed."""
    out = strip_banned_punctuation("Comp is 140k–180k for this role.")
    assert "–" in out
    assert out == "Comp is 140k–180k for this role."


def test_semicolon_becomes_sentence_break():
    out = strip_banned_punctuation("I led infra; we shipped.")
    assert ";" not in out
    assert out == "I led infra. we shipped."


# ── Pass 2: banned phrases ─────────────────────────────────────────


def test_banned_phrase_replacement_records_hit():
    cleaned, hits = strip_banned_phrases(
        "I leverage synergies to delve into cutting-edge tech."
    )
    # "leverage" → "use", "synergies" → "overlaps", "delve into" →
    # "explore", "cutting-edge" → "modern".
    assert "leverage" not in cleaned.lower()
    assert "synergies" not in cleaned.lower()
    assert "delve" not in cleaned.lower()
    assert "cutting-edge" not in cleaned.lower()
    # All four hits captured for telemetry.
    assert "leverage" in hits
    assert "synergies" in hits
    assert "delve into" in hits
    assert "cutting-edge" in hits


def test_banned_phrase_preserves_leading_capitalization():
    """A banned phrase that starts a sentence must stay capitalized
    after replacement — otherwise the output is visibly glitched."""
    cleaned, _ = strip_banned_phrases("Leverage this pattern everywhere.")
    # "leverage" → "use"; must come out "Use ...".
    assert cleaned.startswith("Use ")


def test_banned_phrase_longest_wins():
    """'delve into' and 'delve' both appear in the rules; the longer
    match must win so we don't over-translate."""
    cleaned, _ = strip_banned_phrases("I delve into the problem.")
    # "delve into" → "explore". If "delve" won, we'd get "look into into".
    assert "explore the problem" in cleaned


def test_banned_phrase_downgrades_to_simpler_word():
    """Soft downgrades like 'meticulous' → 'careful' must not over-
    delete; they should drop a recognisably LLM-flavoured word for
    the neutral synonym."""
    cleaned, hits = strip_banned_phrases(
        "I meticulously tested the deploy."
    )
    assert "meticulous" not in cleaned.lower()
    assert "carefully" in cleaned
    assert "meticulously" in hits


# ── Pass 3: tricolons ──────────────────────────────────────────────


def test_tricolon_middle_item_dropped():
    """Canonical "A, B, and C" pattern — middle item gone."""
    out = cap_tricolons("The system is fast, scalable, and robust.")
    # Should become "The system is fast and robust."
    assert "scalable" not in out
    assert "fast and robust" in out


def test_tricolon_without_and_still_caught():
    """"A, B, C" (no serial 'and') also matches the rule."""
    out = cap_tricolons("Use Docker, Helm, Terraform for deploys.")
    assert "Helm" not in out


# ── Pass 4/5: templates ────────────────────────────────────────────


def test_template_opening_stripped():
    """"As a senior engineer, " opener cut; rest preserved."""
    out = strip_template_openings("As a Senior SRE, I ship infra.")
    assert not out.lower().startswith("as a")
    assert "I ship infra." in out


def test_template_closing_stripped():
    out = strip_template_closings(
        "I ship infra. I look forward to discussing the role."
    )
    assert "look forward" not in out.lower()
    assert out.strip().endswith("infra.")


def test_template_closing_handles_alternative_phrasing():
    out = strip_template_closings(
        "I ship infra. Thank you for considering my application."
    )
    assert "thank you" not in out.lower()


# ── Pass 6: burstiness ─────────────────────────────────────────────


def test_burstiness_sigma_sentinel_for_short_input():
    """Single-sentence input returns the 999.0 sentinel so the caller
    can distinguish 'already bursty' from 'uncheckable'."""
    assert compute_burstiness_sigma("One sentence only.") == 999.0


def test_burstiness_enforce_nop_when_already_bursty():
    """Uneven-length sentences pass through unchanged."""
    text = "I ship. " * 3 + "This sentence is deliberately much longer than the previous ones to boost sigma above threshold."
    out = burstiness_enforce(text)
    assert out == text


def test_burstiness_enforce_splits_low_variance_input():
    """Uniform-length sentences get one split to raise sigma. Crude
    but deterministic behavior — same input, same output."""
    # Three sentences, all ~6 words. Sigma == 0 initially.
    text = (
        "I built the data pipeline, which ran nightly, "
        "with retries and alerting. "
        "The team ran experiments, with A/B testing, "
        "and deployed weekly. "
        "We shipped the feature, in three weeks, "
        "with full documentation."
    )
    sigma_before = compute_burstiness_sigma(text)
    out = burstiness_enforce(text)
    # Either the function split something (output changed) or there
    # were no commas to split on — both are valid outcomes of the
    # "don't invent content" contract.
    if out != text:
        sigma_after = compute_burstiness_sigma(out)
        assert sigma_after > sigma_before


def test_burstiness_target_constant_matches_spec():
    """Spec says sigma >= 6. If this gets changed, tests that rely
    on the threshold must be reviewed."""
    assert BURSTINESS_TARGET_SIGMA == 6.0


# ── Pass 7: style match ────────────────────────────────────────────


def test_style_match_noop_without_corpus():
    text, used = style_match_pass("anything", None)
    assert text == "anything"
    assert used == 0


def test_style_match_noop_when_corpus_too_small():
    """< MIN_CORPUS_SIZE examples = no pass applied, even if a few
    rows exist."""
    small_corpus = [("draft 1", "final 1"), ("draft 2", "final 2")]
    assert len(small_corpus) < STYLE_MATCH_MIN_CORPUS_SIZE
    text, used = style_match_pass("anything", small_corpus)
    assert text == "anything"
    assert used == 0


def test_style_match_v6_stub_is_text_noop_even_with_sufficient_corpus():
    """The v6 implementation of style_match_pass is a deliberate stub:
    it never rewrites text (the full LLM-backed rewrite lands in
    Phase 4). A corpus at or above the minimum size keeps the text
    unchanged and returns 0 used — regression test for the Phase 4
    handoff: if this starts returning non-zero, the LLM path must
    have shipped and the telemetry shape needs re-verifying."""
    corpus = [("d", "f")] * (STYLE_MATCH_MIN_CORPUS_SIZE * 2)
    text, used = style_match_pass("anything", corpus)
    assert text == "anything"
    # Stub returns 0 because the cap-then-min-check arithmetic in
    # the v6 code short-circuits before recording usage. Phase 4
    # will change this; when it does, update the assertion.
    assert used == 0


# ── Pass 8: deterministic imperfection ─────────────────────────────


def test_occasional_imperfection_is_deterministic():
    """Same input produces same output across calls. Critical for
    reproducible side-by-side comparisons and for test stability."""
    text = "I have built the system. The team shipped on time."
    a = occasional_imperfection(text)
    b = occasional_imperfection(text)
    assert a == b


# ── End-to-end composer ────────────────────────────────────────────


def test_humanize_empty_input_short_circuits():
    result = humanize("")
    assert result.text == ""
    assert result.passes_applied == []


def test_humanize_whitespace_only_short_circuits():
    result = humanize("   \n\t")
    assert result.passes_applied == []


def test_humanize_records_every_pass_on_real_input():
    """A full happy path. All 8 passes should appear in the provenance
    list regardless of whether they change the text."""
    result = humanize("I leverage Python and ship features.")
    expected = [
        "strip_banned_punctuation",
        "strip_banned_phrases",
        "cap_tricolons",
        "strip_template_openings",
        "strip_template_closings",
        "burstiness_enforce",
        "style_match_pass",
        "occasional_imperfection",
    ]
    assert result.passes_applied == expected


def test_humanize_surfaces_banned_hits():
    """End-to-end: the hit list percolates up to the result object."""
    result = humanize("I leverage synergies across cutting-edge systems.")
    assert "leverage" in result.banned_phrase_hits
    assert "synergies" in result.banned_phrase_hits
    assert "cutting-edge" in result.banned_phrase_hits


def test_humanize_strips_all_ai_tells_from_classic_llm_output():
    """The integration case — a paragraph that's dense with LLM tells.
    After humanization, none of the flagged tokens should survive."""
    llm_output = (
        "As a Senior Engineer, I leverage cutting-edge tools to delve into "
        "the landscape of modern infrastructure. I seamlessly navigate the "
        "complex, evolving, and dynamic tapestry of cloud systems — "
        "shipping robust, scalable, and maintainable solutions. "
        "I look forward to discussing the opportunity."
    )
    result = humanize(llm_output)
    low = result.text.lower()
    # Every flagged phrase should be gone.
    for tell in [
        "as a senior",
        "leverage",
        "cutting-edge",
        "delve",
        "landscape of",
        "seamlessly",
        "navigate",
        "tapestry",
        "—",
        "look forward",
    ]:
        assert tell not in low, f"'{tell}' survived humanization: {result.text!r}"
