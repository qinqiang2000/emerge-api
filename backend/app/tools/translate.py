"""Per-page document translation — review-mode UX only.

Two branches share one return shape:

- **textlayer mode** — any sidecar with `spans>0`, regardless of `scanned`.
  Covers electronic PDFs (fitz vector spans) AND scanned / raster docs
  whose textlayer OCR fallback succeeded (`text_source="ocr"`). We send
  the originals as a JSON array (text-only, no image) to a cheap
  translator LLM and pair each translation with the bbox we already have.
  No second vision call here — reusing the OCR'd spans means we pay for
  page OCR once (inside `extract_textlayer`) rather than twice.
- **vision mode** — fallback when the sidecar has zero spans (OCR was
  skipped or returned nothing usable). We ask the LLM to OCR + locate +
  translate in one shot, returning `[y0,x0,y1,x1]` normalised to 0–1000
  which we convert back to PDF-page units so the frontend renderer can
  treat both modes uniformly.

Hard rules respected:
- Translate is its own provider call path. It does NOT recurse into the
  Claude agent SDK and does NOT share prompts with extract / labeler /
  proposer. Four-LLM separation; this is the fifth axis (translator).
- bbox / spans NEVER feed back into the extract or runtime prompt. The
  sidecar is consumed by the review overlay (and any CLI client) only —
  this file is the only producer.
- No image few-shot. Vision mode sends raw page + prompt; no example I/O.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.provider import get_provider_for_model
from app.provider.base import ContentBlock, ImageBlock, TextBlock
from app.tools.docs import read_doc_image
from app.tools.textlayer import extract_textlayer
from app.workspace.atomic import atomic_write_text
from app.workspace.paths import (
    doc_translate_dir,
    doc_translate_path,
    project_json_path,
)


# Translator system prompt is identical across modes — the user message
# carries the mode-specific instruction. Kept tiny because the cheap
# translator LLM does not need context beyond "translate honestly".
_TRANSLATE_SYSTEM = (
    "你是文档翻译助手。严格按要求输出 JSON；不要解释、不要包装、不要多余字段。"
)


def _read_project_translate_override(
    workspace: Path, slug: str,
) -> str | None:
    """Return `project.json.translate_model` if explicitly set, else None.

    Mirrors `_read_project_labeler_override` in `pre_label.py`. Missing file
    / unparseable JSON / missing key / null value all collapse to None
    (= "no override; use env default")."""
    pj = project_json_path(workspace, slug)
    if not pj.exists():
        return None
    try:
        blob = json.loads(pj.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return blob.get("translate_model") or None


def resolve_translate_model(workspace: Path, slug: str) -> str:
    """Priority: project.json.translate_model > settings env default > hardcode.

    Unlike `_resolve_labeler_model`, we never error: there is always a
    fallback because translate has a built-in safe default
    (`gemini-flash-lite-latest`) — translation is a UX nicety, not a config
    contract."""
    override = _read_project_translate_override(workspace, slug)
    if override:
        return override
    return get_settings().default_translate_model or "gemini-flash-lite-latest"


# Response-schemas — kept in module scope so they're built once per process.

_TEXTLAYER_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "translated": {"type": "string"},
                },
                "required": ["index", "translated"],
            },
        },
    },
    "required": ["items"],
}


_VISION_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "bbox": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "original": {"type": "string"},
                    "translated": {"type": "string"},
                },
                "required": ["bbox", "original", "translated"],
            },
        },
    },
    "required": ["lines"],
}


def _textlayer_prompt(target_lang: str, originals: list[str]) -> str:
    """JSON-array translate prompt. Returns a single string that carries the
    instruction + the array of originals — the model is asked to return an
    array of identical length with one `translated` field per item.

    `zh` is explicitly named as 简体中文; other lang codes are passed
    through verbatim (the model is multilingual enough to handle ISO codes).
    """
    lang_hint = (
        "简体中文" if target_lang == "zh" else target_lang
    )
    payload = json.dumps(
        [{"index": i, "text": t} for i, t in enumerate(originals)],
        ensure_ascii=False,
    )
    return (
        f"把下面 JSON array 里每个 `text` 翻译成 {lang_hint}。"
        f"返回的 array 每项必须包含 `index`（原 index 整数）和 `translated`（译文字符串）。"
        f"不要合并、不要跳过、不要重新排序——每个原 index 出现且仅出现一次。"
        f"已经是目标语言的项直接复制原文。不要解释，只返回 JSON。\n\n"
        f"{payload}"
    )


def _vision_prompt(target_lang: str) -> str:
    lang_hint = (
        "简体中文" if target_lang == "zh" else target_lang
    )
    return (
        f"你是文档 OCR + 翻译助手。提取图片中所有可见文本行，按出现顺序输出。"
        f"每行三个字段：\n"
        f"`bbox`：`[y0,x0,y1,x1]` 归一化到 0–1000（左上角原点，y 向下）；"
        f"`original`：原文（保留原语言）；"
        f"`translated`：翻译成 {lang_hint}。"
        f"表格的每个 cell 是独立一行。原文已经是目标语言时 `translated` 直接等于 `original`。"
        f"不要解释，直接返回 JSON。"
    )


def _denormalise_bbox(
    bbox_norm: list[int], page_w: float, page_h: float,
) -> list[float]:
    """Gemini returns `[y0, x0, y1, x1]` normalised to 0–1000 — convert back
    to PDF-page units `[x0, y0, x1, y1]` so the sidecar carries one
    consistent shape regardless of mode."""
    if len(bbox_norm) != 4:
        raise ValueError(
            f"vision bbox must be 4 ints, got {bbox_norm!r}"
        )
    y0_n, x0_n, y1_n, x1_n = bbox_norm
    return [
        (float(x0_n) / 1000.0) * page_w,
        (float(y0_n) / 1000.0) * page_h,
        (float(x1_n) / 1000.0) * page_w,
        (float(y1_n) / 1000.0) * page_h,
    ]


async def translate_page(
    workspace: Path,
    project_id: str,
    filename: str,
    *,
    page: int,
    target_lang: str = "zh",
    model_id: str | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Translate one page of one doc, picking textlayer vs vision automatically.

    Cache key is `(filename, page, target_lang, mode, model_id)`. Changing
    any of those misses; `force_refresh=True` (Shift+T from the frontend)
    bypasses the read but still atomically writes the result back so the
    next call re-warms. Provider failures do NOT cache — exception bubbles.

    Returns (BOTH branches normalise to this shape):
        {
            "filename": str, "page": int, "target_lang": str, "model_id": str,
            "mode": "textlayer" | "vision",
            "page_w": float, "page_h": float,
            "image_w": int, "image_h": int,
            "lines": [
                {"bbox": [x0, y0, x1, y1], "original": str, "translated": str}
            ],
            "input_tokens": int, "output_tokens": int,
        }

    `bbox` is ALWAYS in PDF page units (top-left origin, matching fitz). The
    vision branch converts Gemini's normalised `[y0,x0,y1,x1]` 0–1000 back
    to this shape using `page_w` / `page_h` from the textlayer sidecar.
    """
    mid = model_id or resolve_translate_model(workspace, project_id)

    sidecar_for_textlayer = await extract_textlayer(
        workspace, project_id, filename, page=page,
    )
    # `extract_textlayer` already validated page range + doc existence and
    # populated `page_w`, `page_h`, `image_w`, `image_h` even for scanned /
    # image branches. Reuse those numbers for the vision-mode bbox
    # denormalisation so both branches produce identical canvas dims.
    page_w = float(sidecar_for_textlayer["page_w"])
    page_h = float(sidecar_for_textlayer["page_h"])
    image_w = int(sidecar_for_textlayer["image_w"])
    image_h = int(sidecar_for_textlayer["image_h"])
    spans = sidecar_for_textlayer.get("spans") or []
    use_textlayer = len(spans) > 0
    mode = "textlayer" if use_textlayer else "vision"

    cache = doc_translate_path(
        workspace, project_id, filename,
        page=page, target_lang=target_lang, mode=mode, model_id=mid,
    )
    if cache.exists() and not force_refresh:
        return json.loads(cache.read_text())

    doc_translate_dir(workspace, project_id, filename).mkdir(
        parents=True, exist_ok=True,
    )

    provider = get_provider_for_model(mid)

    if use_textlayer:
        originals = [str(s.get("text", "")) for s in spans]
        prompt = _textlayer_prompt(target_lang, originals)
        result = await provider.extract(
            model_id=mid,
            system_prompt=_TRANSLATE_SYSTEM,
            user_content=[TextBlock(text=prompt)],
            response_schema=_TEXTLAYER_RESPONSE_SCHEMA,
        )
        # Gemini's JSON mode returns the schema's root type verbatim. For an
        # array response_schema, `raw_json` may arrive as either the bare
        # list or wrapped in a single-key dict depending on schema-mode
        # version — accept both shapes defensively.
        raw = result.raw_json
        if isinstance(raw, dict) and len(raw) == 1:
            (only_val,) = raw.values()
            translated_arr = only_val
        else:
            translated_arr = raw
        if not isinstance(translated_arr, list):
            raise ValueError(
                f"translator returned non-array payload: {type(translated_arr).__name__}"
            )
        # Align by index — robust against LLMs that merge / drop / reorder
        # items. Missing indices fall back to the original text so the page
        # always renders with hotspots; users see which lines actually got
        # translated. Length mismatch is logged but not fatal.
        by_index: dict[int, str] = {}
        for item in translated_arr:
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            if not isinstance(idx, int):
                continue
            by_index[idx] = str(item.get("translated", ""))
        lines = []
        for i, span in enumerate(spans):
            original = str(span.get("text", ""))
            translated_text = by_index.get(i, original)
            lines.append({
                "bbox": [float(v) for v in span.get("bbox", [0, 0, 0, 0])],
                "original": original,
                "translated": translated_text,
            })
    else:
        # Vision mode — pull the page image as a base64 ImageBlock (PDF or
        # native raster) and ask for OCR + bbox + translation in one shot.
        img = await read_doc_image(
            workspace, project_id, filename, page=page,
        )
        prompt = _vision_prompt(target_lang)
        user_blocks: list[ContentBlock] = [
            TextBlock(text=prompt),
            ImageBlock(media_type=img["mime"], data_b64=img["data"]),
        ]
        result = await provider.extract(
            model_id=mid,
            system_prompt=_TRANSLATE_SYSTEM,
            user_content=user_blocks,
            response_schema=_VISION_RESPONSE_SCHEMA,
        )
        raw = result.raw_json
        if not isinstance(raw, dict) or "lines" not in raw:
            raise ValueError(
                f"vision translator returned malformed payload: {type(raw).__name__}"
            )
        lines = []
        for entry in raw["lines"]:
            if not isinstance(entry, dict):
                continue
            bbox_norm = entry.get("bbox") or [0, 0, 0, 0]
            pdf_bbox = _denormalise_bbox(
                [int(v) for v in bbox_norm], page_w, page_h,
            )
            lines.append({
                "bbox": pdf_bbox,
                "original": str(entry.get("original", "")),
                "translated": str(entry.get("translated", "")),
            })

    payload: dict[str, Any] = {
        "filename": filename,
        "page": page,
        "target_lang": target_lang,
        "model_id": mid,
        "mode": mode,
        "page_w": page_w,
        "page_h": page_h,
        "image_w": image_w,
        "image_h": image_h,
        "lines": lines,
        "input_tokens": int(result.input_tokens or 0),
        "output_tokens": int(result.output_tokens or 0),
    }
    atomic_write_text(cache, json.dumps(payload, ensure_ascii=False))
    return payload
