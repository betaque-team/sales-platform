"""Boolean search query parser for the JobsPage search bar (F240).

The previous behavior was a single ILIKE substring across (title,
company_name, location_raw). Power users (khushi.jain feedback ticket
"Search Bar Query") asked for boolean syntax — AND / OR / NOT, quoted
phrases, and Google-style minus-prefix exclusions.

Design choice: build it as a thin parser that compiles the user's
query string into a SQLAlchemy expression. Alternative was Postgres
`tsquery` full-text indexes, rejected because:
  - Needs an Alembic migration + reindex of ~60k jobs
  - Stemming/language config changes behavior for every existing user
  - The win for our use case (substring across 3 columns) is small;
    boolean composition is the actual missing piece, not relevance scoring

The parser is **opt-in via syntax**: a query without any operators or
quotes falls through to the existing single-substring ILIKE branch
(`q.matches_any(needle)` is what the legacy path does). Existing users
who type "bitwarden" keep getting the same behavior. Users who type
`security AND remote NOT manager` get smart parsing.

Supported syntax:

  cloud kubernetes              → both must match (implicit AND)
  cloud OR kubernetes           → either matches
  "site reliability"            → matches the literal phrase as one token
  security NOT manager          → matches "security" excluding any
                                  row that also matches "manager"
  -manager security             → same as above (Google-style minus)
  (cloud OR kubernetes) AND remote
                                → grouping with parentheses

Operator precedence (highest → lowest): NOT > AND > OR. Matches the
universal SQL/programming convention so users who know boolean logic
get unsurprising results.

Case sensitivity: operator keywords (AND/OR/NOT) are matched
case-INsensitively for typing convenience but rendered as `or_`/`and_`
in SQL — the matching itself stays case-insensitive (ILIKE) for the
terms.

Empty groups (`()`) and trailing operators (`security AND`) raise
``SearchQueryError`` so the handler can return a 400 with a helpful
message instead of producing a confusing empty result set.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Iterator

from sqlalchemy import and_, not_, or_
from sqlalchemy.sql import ClauseElement

from app.utils.sql import escape_like


class SearchQueryError(ValueError):
    """Raised when the user's query has a syntax error.

    The handler catches this and returns a 400 with the message in
    ``detail`` so the frontend can render a useful inline error
    instead of a generic "no results" empty state.
    """


# Operator keywords. Matched case-insensitively. NOT also accepts
# the leading-hyphen Google-style form (handled separately in the
# tokenizer so `-manager` is one token, not two).
_OPS = {"AND", "OR", "NOT"}


@dataclass(frozen=True)
class _Term:
    """A single search term — a literal substring to match against
    title / company / location via ILIKE."""
    text: str


@dataclass(frozen=True)
class _BinOp:
    op: str            # "AND" | "OR"
    left: "_Node"
    right: "_Node"


@dataclass(frozen=True)
class _Not:
    child: "_Node"


_Node = _Term | _BinOp | _Not


# ── Tokenizer ────────────────────────────────────────────────────────────────

def _tokenize(s: str) -> list[str]:
    """Split the query into tokens.

    Uses ``shlex`` so quoted phrases survive as single tokens
    ("site reliability" → one token "site reliability"). Then
    rewrites ``-foo`` into ``NOT foo`` so the rest of the parser
    only deals with one form.
    """
    if not s.strip():
        return []
    try:
        # posix=True handles "" quoting; punctuation_chars=False so
        # parens stay attached and we split them out manually.
        raw_tokens = shlex.split(s, posix=True)
    except ValueError as e:
        # Unbalanced quote
        raise SearchQueryError(f"Unbalanced quote in search query: {e}")

    out: list[str] = []
    for tok in raw_tokens:
        # Split parens off the start/end of any token so `(cloud` →
        # `(`, `cloud`. shlex doesn't do this — we want them as
        # standalone operators.
        i = 0
        while i < len(tok) and tok[i] == "(":
            out.append("(")
            i += 1
        rest = tok[i:]
        # Strip trailing parens
        trailing = 0
        while rest.endswith(")"):
            rest = rest[:-1]
            trailing += 1
        if rest:
            # Google-style minus: `-foo` → NOT foo. Don't trigger on
            # `-` inside a token (e.g. `dev-ops`).
            if rest.startswith("-") and len(rest) > 1:
                out.append("NOT")
                out.append(rest[1:])
            else:
                out.append(rest)
        for _ in range(trailing):
            out.append(")")
    return out


# ── Parser ───────────────────────────────────────────────────────────────────
#
# Grammar (recursive descent, conventional precedence):
#
#   expr   ::= or_expr
#   or_expr  ::= and_expr ("OR" and_expr)*
#   and_expr ::= not_expr (("AND" | <implicit>) not_expr)*
#   not_expr ::= "NOT" not_expr | atom
#   atom   ::= TERM | "(" expr ")"

class _Parser:
    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.pos = 0

    def _peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _consume(self) -> str:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _is_op(self, tok: str | None, *names: str) -> bool:
        if tok is None:
            return False
        return tok.upper() in names

    def parse(self) -> _Node:
        node = self._or_expr()
        if self.pos != len(self.tokens):
            raise SearchQueryError(
                f"Unexpected token at position {self.pos}: '{self.tokens[self.pos]}'"
            )
        return node

    def _or_expr(self) -> _Node:
        left = self._and_expr()
        while self._is_op(self._peek(), "OR"):
            self._consume()  # OR
            if self._peek() is None:
                raise SearchQueryError("Trailing OR with no right-hand operand")
            right = self._and_expr()
            left = _BinOp(op="OR", left=left, right=right)
        return left

    def _and_expr(self) -> _Node:
        left = self._not_expr()
        while True:
            tok = self._peek()
            if tok is None:
                break
            if self._is_op(tok, "OR", ")"):
                break
            if self._is_op(tok, "AND"):
                self._consume()  # AND
                if self._peek() is None:
                    raise SearchQueryError("Trailing AND with no right-hand operand")
                right = self._not_expr()
            else:
                # Implicit AND (juxtaposition). The next token is a
                # term or NOT or `(`, fold it in.
                right = self._not_expr()
            left = _BinOp(op="AND", left=left, right=right)
        return left

    def _not_expr(self) -> _Node:
        if self._is_op(self._peek(), "NOT"):
            self._consume()  # NOT
            if self._peek() is None:
                raise SearchQueryError("Trailing NOT with no operand")
            return _Not(child=self._not_expr())
        return self._atom()

    def _atom(self) -> _Node:
        tok = self._peek()
        if tok is None:
            raise SearchQueryError("Empty search query")
        if tok == "(":
            self._consume()  # (
            inner = self._or_expr()
            if self._peek() != ")":
                raise SearchQueryError("Missing closing ')'")
            self._consume()  # )
            return inner
        if tok == ")":
            raise SearchQueryError("Unexpected ')'")
        if self._is_op(tok, "AND", "OR", "NOT"):
            raise SearchQueryError(
                f"Unexpected operator '{tok}' — expected a search term"
            )
        self._consume()
        return _Term(text=tok)


# ── Detection ────────────────────────────────────────────────────────────────

# Cheap regex that triggers the boolean-mode path. Conservative: a
# user's bare query like `aws engineer` wouldn't hit this (the words
# AND/OR/NOT only count as operators when they're standalone tokens
# in upper case). We don't want `and-fragments` or `cocoa or` to
# accidentally be interpreted as boolean.
_BOOLEAN_TRIGGERS = re.compile(
    r"\b(AND|OR|NOT)\b"      # uppercase operators as whole words
    r"|\""                   # quoted phrase
    r"|(^|\s)-\S"            # leading-minus exclusion
    r"|[()]",                # grouping parens
)


def is_boolean_query(s: str) -> bool:
    """Return True if the user's query string looks like boolean
    syntax. False = fall through to the legacy single-substring
    ILIKE branch."""
    return bool(_BOOLEAN_TRIGGERS.search(s or ""))


# ── Compile to SQLAlchemy ────────────────────────────────────────────────────

def parse(query: str) -> _Node:
    """Parse the query string into an AST. Raises SearchQueryError
    on syntax errors so the handler can 400."""
    tokens = _tokenize(query)
    if not tokens:
        raise SearchQueryError("Empty search query")
    return _Parser(tokens).parse()


def compile_to_clause(
    node: _Node, term_to_clause
) -> ClauseElement:
    """Walk the AST, calling `term_to_clause(text)` for each leaf.

    `term_to_clause` returns the SQLAlchemy expression for a single
    term match across the columns the caller cares about (e.g. an
    OR over title/company/location ILIKEs). Keeping it injectable
    lets this module stay column-agnostic — any caller can compile
    queries against any tables.
    """
    if isinstance(node, _Term):
        return term_to_clause(node.text)
    if isinstance(node, _Not):
        return not_(compile_to_clause(node.child, term_to_clause))
    if isinstance(node, _BinOp):
        l = compile_to_clause(node.left, term_to_clause)
        r = compile_to_clause(node.right, term_to_clause)
        return and_(l, r) if node.op == "AND" else or_(l, r)
    raise SearchQueryError(f"Unknown AST node type: {type(node).__name__}")


def term_clause_factory(*columns):
    """Build a `term_to_clause` for a list of SQLAlchemy column
    objects. Each term matches if ANY of the columns ILIKEs it.

    The columns are passed at the call site so this module doesn't
    import any model — keeps the parser unit-testable without a DB.
    """
    def _build(text: str):
        needle = f"%{escape_like(text)}%"
        # OR across the columns so a term matches if any column
        # contains it. Same per-term semantics as the legacy single-
        # ILIKE branch — the boolean composition operates over these
        # ANY-of-columns results.
        return or_(*(c.ilike(needle, escape="\\") for c in columns))
    return _build
