"""Human-readable, filesystem-safe handles ("slugs").

A slug is what makes emerge's filesystem spine legible to its agent colleague:
`teams/honor/us-invoice/` reads; `teams/t_7fp7mzchoxff/p_3k9x/` does not. Both
projects (`tools.projects`) and teams (`auth.store`) derive their on-disk folder
name from the human name through here, so the rule is defined once.

The opaque `t_…`/`p_…` ids still exist — they live INSIDE the json as stable
reference anchors (a rename changes the slug, never the id). The slug is only
the directory name / URL handle, exactly mirroring the project model.
"""
from __future__ import annotations

import re
import secrets
import unicodedata
from collections.abc import Iterable
from datetime import datetime, timezone


# `/` and `\` would create unintended subdirs, NUL terminates C-strings, and
# other control chars round-trip badly through shells / URLs. Whitespace is
# normalized to a single `-` separately so we don't lose word boundaries in
# CJK + Latin mixes like "Q4 美国发票".
_SLUG_DROP_CHARS = re.compile(r"[\\/\x00-\x1f\x7f]")
_SLUG_WHITESPACE = re.compile(r"\s+")
_SLUG_COLLAPSE_DASH = re.compile(r"-{2,}")

# Hard cap. 64 chars matches the route-side `safe_slug` upper bound — derive
# must not produce something the validator will reject.
SLUG_MAX_LEN = 64


def derive_slug(name: str, *, fallback_prefix: str = "project") -> str:
    """Human name → fs-safe + URL-safe handle.

    Rules (in order):
      1. NFKC + `.strip().lower()` for width / case / whitespace normalization.
      2. Replace any whitespace run with `-` so words stay separated.
      3. Drop NUL / control chars / `/` / `\\` (filesystem hostile).
      4. Collapse consecutive `-` into one, then trim leading/trailing `-`.
      5. Truncate to `SLUG_MAX_LEN`.
      6. Empty result falls back to `{fallback_prefix}-YYYY-MM-DD-<3 base36>` so
         we always produce a valid folder name.

    Unicode is intentionally **preserved** — CJK, accents, emoji round-trip
    unchanged. The frontend uses `encodeURIComponent` on slug path segments so
    non-ASCII handles are safe in URLs.
    """
    if not isinstance(name, str):
        name = ""
    # NFKC normalizes width / compat forms (full-width digits → half-width,
    # etc.) so visually-identical inputs collide deterministically.
    normalized = unicodedata.normalize("NFKC", name).strip().lower()
    # Replace whitespace runs *before* dropping bad chars so "foo / bar"
    # becomes "foo---bar" (then collapse) instead of "foobar".
    normalized = _SLUG_WHITESPACE.sub("-", normalized)
    normalized = _SLUG_DROP_CHARS.sub("", normalized)
    normalized = _SLUG_COLLAPSE_DASH.sub("-", normalized).strip("-")
    if len(normalized) > SLUG_MAX_LEN:
        normalized = normalized[:SLUG_MAX_LEN].rstrip("-")
    if not normalized:
        # secrets.token_hex(2) is 4 hex chars; slice to 3 to keep slug stable
        # in length and out of the random base36 namespace used by ids.
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rand = secrets.token_hex(2)[:3]
        return f"{fallback_prefix}-{today}-{rand}"
    return normalized


def ensure_unique_slug(base: str, taken: Iterable[str], *, max_len: int = SLUG_MAX_LEN) -> str:
    """Append `-2`, `-3`, … until `base` is free of `taken`. `base` is returned
    untouched when it doesn't collide. The candidate is re-trimmed so the
    suffixed result still fits `max_len`."""
    seen = set(taken)
    if base not in seen:
        return base
    n = 2
    while True:
        suffix = f"-{n}"
        room = max_len - len(suffix)
        head = base[:room].rstrip("-") if len(base) > room else base
        candidate = f"{head}{suffix}"
        if candidate not in seen:
            return candidate
        n += 1
