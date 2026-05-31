"""JSON-Schema → emerge `SchemaField` transcoder.

Customers arrive with a prompt config they already run elsewhere — typically a
Gemini / OpenAI structured-output bundle whose field shape is a *JSON-Schema*
(``type``/``properties``/``items``/``anyOf``), not emerge's flat
``[{name, type, description, ...}]`` list. Before this module, importing such a
file meant the agent hand-converting it via trial-and-error edits, one
fail-fast validation error per re-import round-trip (see the chinhin.yaml
21-turn death spiral, INSIGHTS). This is the bridge: pure, I/O-free, best-effort
transcode so "drop your existing prompt, the schema imports" actually works.

It is deliberately lenient — it gets the *structure* right (unwrap the record
object, fold ``required`` arrays into per-field booleans, drop nullable
``anyOf`` null-branches, lowercase Gemini's UPPERCASE types). Residual problems
are left for `SchemaField` validation to flag (now aggregated), rather than
guessed at here.

Output is a list of `SchemaField`-shaped *dicts* (not model instances) so the
caller runs them through the same `SchemaField.model_validate` path every other
import takes — the transcoder never bypasses validation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# JSON-Schema `string` formats emerge's StringFormat understands; anything else
# (email, uri, uuid, …) is dropped — emerge has no slot for it.
_KEEP_FORMATS = {"date", "date-time", "time"}

# Where a record's field schema commonly hides inside a foreign prompt bundle.
_NESTED_SCHEMA_KEYS = ("json_schema", "response_schema", "responseSchema", "schema")


@dataclass
class TranscodeResult:
    fields: list[dict[str, Any]]
    # Human-readable trail of what the transcoder did, surfaced back to the
    # agent/UI so the conversion is self-explaining ("merged 2 variant
    # branches; 29 fields; resolved 12 nullable").
    notes: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return "; ".join(self.notes)


def transcode_to_schema_fields(parsed: Any) -> TranscodeResult | None:
    """Best-effort convert a parsed JSON-Schema / foreign prompt config into a
    list of `SchemaField`-shaped dicts.

    Returns ``None`` when ``parsed`` doesn't look like a JSON-Schema at all —
    the caller turns that into a teaching error. Raising is reserved for the
    validation layer downstream.
    """
    if not isinstance(parsed, dict):
        return None

    notes: list[str] = []
    node = _locate_schema_node(parsed, notes)
    if node is None:
        return None

    record = _unwrap_to_record(node, notes)
    if record is None:
        return None

    props = record.get("properties")
    if not isinstance(props, dict) or not props:
        return None

    required = _required_set(record)
    fields: list[dict[str, Any]] = []
    ctx = _Counters()
    for name, sub in props.items():
        conv = _convert_node(sub, ctx)
        if conv is None:
            ctx.dropped.append(str(name))
            continue
        conv["name"] = name
        if name in required:
            conv["required"] = True
        fields.append(conv)

    if not fields:
        return None

    notes.append(f"{len(fields)} top-level fields")
    if ctx.nullable_resolved:
        notes.append(f"resolved {ctx.nullable_resolved} nullable anyOf")
    if ctx.dropped_formats:
        notes.append(f"dropped {ctx.dropped_formats} unsupported format(s)")
    if ctx.dropped:
        notes.append(f"could not convert {len(ctx.dropped)} field(s): {', '.join(ctx.dropped)}")
    return TranscodeResult(fields=fields, notes=notes)


@dataclass
class _Counters:
    nullable_resolved: int = 0
    dropped_formats: int = 0
    dropped: list[str] = field(default_factory=list)


def _locate_schema_node(parsed: dict[str, Any], notes: list[str]) -> dict[str, Any] | None:
    """Find the JSON-Schema node that describes the extraction record."""
    # Gemini-style prompt config: field schema lives under prompt_template.
    pt = parsed.get("prompt_template")
    if isinstance(pt, dict):
        for key in _NESTED_SCHEMA_KEYS:
            if isinstance(pt.get(key), dict):
                notes.append("detected prompt-config bundle (prompt_template)")
                return pt[key]
    # Bundle with the schema hung directly off the root.
    for key in _NESTED_SCHEMA_KEYS:
        if isinstance(parsed.get(key), dict):
            notes.append(f"detected schema under '{key}'")
            return parsed[key]
    # The root *is* a JSON-Schema.
    if _looks_like_json_schema(parsed):
        notes.append("detected raw JSON-Schema root")
        return parsed
    return None


def _looks_like_json_schema(node: dict[str, Any]) -> bool:
    if any(k in node for k in ("properties", "items", "anyOf", "oneOf")):
        return True
    t = _norm_type(node.get("type"))
    return t in ("object", "array", "string", "number", "integer", "boolean")


def _unwrap_to_record(node: dict[str, Any], notes: list[str]) -> dict[str, Any] | None:
    """Peel array / anyOf wrappers until we reach the object whose
    ``properties`` are the per-document fields. Multiple object branches
    (e.g. invoice-variant vs receipt-variant) are merged into one union."""
    for _ in range(8):  # bounded — guards against pathological self-reference
        if not isinstance(node, dict):
            return None
        branches = node.get("anyOf") or node.get("oneOf")
        if isinstance(branches, list):
            objs = [b for b in branches if isinstance(b, dict) and _has_object_shape(b)]
            if len(objs) > 1:
                notes.append(f"merged {len(objs)} variant branches")
                node = _merge_objects(objs)
                continue
            if len(objs) == 1:
                node = objs[0]
                continue
            # No object branch to unwrap into.
            non_null = [b for b in branches if isinstance(b, dict) and _norm_type(b.get("type")) != "null"]
            if len(non_null) == 1:
                node = non_null[0]
                continue
            return None
        t = _norm_type(node.get("type"))
        if t == "array" or (t is None and "items" in node):
            items = node.get("items")
            if not isinstance(items, dict):
                return None
            notes.append("unwrapped array root → element object")
            node = items
            continue
        if "properties" in node or t == "object":
            return node
        return None
    return None


def _has_object_shape(node: dict[str, Any]) -> bool:
    return "properties" in node or _norm_type(node.get("type")) == "object"


def _merge_objects(objs: list[dict[str, Any]]) -> dict[str, Any]:
    """Union the properties of several object branches. On name collision keep
    the richer (longer-description) field; union the ``required`` lists."""
    props: dict[str, Any] = {}
    required: set[str] = set()
    for o in objs:
        required |= _required_set(o)
        for name, sub in (o.get("properties") or {}).items():
            prev = props.get(name)
            if prev is None or _desc_len(sub) > _desc_len(prev):
                props[name] = sub
    return {"type": "object", "properties": props, "required": sorted(required)}


def _convert_node(sub: Any, ctx: _Counters) -> dict[str, Any] | None:
    """Convert one JSON-Schema node into a `SchemaField`-shaped dict (no name)."""
    if not isinstance(sub, dict):
        return None

    sub = _resolve_anyof(sub, ctx)
    if sub is None:
        return None

    t = _norm_type(sub.get("type"))
    if t is None:  # infer from structure
        if "properties" in sub:
            t = "object"
        elif "items" in sub:
            t = "array"
        elif "enum" in sub:
            t = "string"
        else:
            return None

    desc = sub.get("description")
    out: dict[str, Any] = {"type": t, "description": desc if isinstance(desc, str) else ""}

    if t == "string":
        enum = sub.get("enum")
        if isinstance(enum, list) and enum and all(isinstance(e, str) for e in enum):
            out["enum"] = enum
        fmt = sub.get("format")
        if isinstance(fmt, str):
            if fmt in _KEEP_FORMATS:
                out["format"] = fmt
            else:
                ctx.dropped_formats += 1
    elif t == "object":
        children: list[dict[str, Any]] = []
        req = _required_set(sub)
        for name, child in (sub.get("properties") or {}).items():
            conv = _convert_node(child, ctx)
            if conv is None:
                ctx.dropped.append(str(name))
                continue
            conv["name"] = name
            if name in req:
                conv["required"] = True
            children.append(conv)
        out["properties"] = children
    elif t == "array":
        item_conv = _convert_node(sub.get("items"), ctx)
        if item_conv is None:
            return None
        item_conv.pop("name", None)
        out["items"] = item_conv

    return out


def _resolve_anyof(sub: dict[str, Any], ctx: _Counters) -> dict[str, Any] | None:
    """Collapse a nullable / union ``anyOf`` (Gemini's nullable idiom) to a
    single branch, carrying the wrapper's description down if the branch lacks
    one."""
    branches = sub.get("anyOf") or sub.get("oneOf")
    if not isinstance(branches, list):
        return sub
    non_null = [b for b in branches if isinstance(b, dict) and _norm_type(b.get("type")) != "null"]
    if not non_null:
        return None
    if len(non_null) < len(branches):
        ctx.nullable_resolved += 1
    objs = [b for b in non_null if _has_object_shape(b)]
    chosen = _merge_objects(objs) if len(objs) > 1 else non_null[0]
    if "description" not in chosen and isinstance(sub.get("description"), str):
        chosen = {**chosen, "description": sub["description"]}
    return chosen


def _norm_type(t: Any) -> str | None:
    """Lowercase Gemini's UPPERCASE types; collapse JSON-Schema ``["x","null"]``
    nullable type-lists to their non-null member."""
    if isinstance(t, list):
        rest = [x for x in t if str(x).lower() != "null"]
        t = rest[0] if rest else "null"
    if t is None:
        return None
    return str(t).lower()


def _required_set(node: dict[str, Any]) -> set[str]:
    req = node.get("required")
    return {r for r in req if isinstance(r, str)} if isinstance(req, list) else set()


def _desc_len(node: Any) -> int:
    if isinstance(node, dict) and isinstance(node.get("description"), str):
        return len(node["description"])
    return 0
