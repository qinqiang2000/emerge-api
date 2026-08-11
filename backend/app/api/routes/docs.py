import json

from fastapi import APIRouter, Depends, HTTPException
from app.auth.deps import bind_workspace, current_ws
from fastapi.responses import FileResponse

from pydantic import BaseModel

from app.api.routes._safety import safe_filename, safe_slug
from app.config import get_settings
from app.tools.docs import delete_doc, image_doc_as_jpeg, pdf_render_page, rename_doc
from app.workspace.paths import doc_meta_path, doc_path


router = APIRouter(dependencies=[Depends(bind_workspace)])


_IMAGE_MEDIA = {"png": "image/png", "jpg": "image/jpeg"}

# Text-shaped docs (extract's text-input path) have no raster: the page route
# serves their raw bytes as UTF-8 text so the review panel can render them
# verbatim. Keep in lockstep with `app.tools.docs._TEXT_EXTS`.
_TEXT_EXTS = {"txt", "md", "json", "csv", "yml", "yaml"}

# Page rasters are immutable: a doc never changes bytes once uploaded
# (filename is a unique slot, the PDF render cache is content-addressed by
# sha). So the browser can cache a page forever and skip the per-page
# conditional revalidation round-trip on every board reopen / page flip.
_PAGE_CACHE = "public, max-age=31536000, immutable"


@router.get("/lab/projects/{slug}/docs/by-name/{filename:path}/pages/{page}")
async def get_page(slug: str, filename: str, page: int, fmt: str = "auto") -> FileResponse:
    """Serve a viewable page bitmap for a doc.

    Filename is the only doc handle (post-d_xxx removal). The `:path` converter
    lets percent-encoded names with spaces or dots through; we still
    defensively validate the result via `safe_filename` to reject path
    separators and traversal segments.

    Resolution is identical across all three formats — only the codec differs.
    `fmt=auto` (default) keeps whichever of PNG / progressive-JPEG is the
    smaller file for that page; `fmt=png` forces lossless; `fmt=jpeg` is the
    board's q85 baseline JPEG. Callers must NOT assume the content type from
    the request: under `auto` the server picks per page, so the response's own
    `Content-Type` is the only truth (browsers sniff it correctly; the
    frontend `<img>` never cared).

    PDF: renders the requested page on demand (cached under
    `.cache/_render/{sha}/p{n}.{png|jpg}`).
    PNG/JPG: page=1 returns the original bytes (or a JPEG transcode of a PNG
    when `fmt=jpeg`); any other page is 404. The chat thumbnails use this
    single URL pattern for both image and PDF attachments."""
    safe_slug(slug)
    safe_filename(filename)
    settings = get_settings()
    jpeg = fmt.lower() in ("jpeg", "jpg")
    meta_p = doc_meta_path(current_ws(), slug, filename)
    if not meta_p.exists():
        raise HTTPException(status_code=404, detail="doc_not_found")
    meta = json.loads(meta_p.read_text())
    ext = str(meta.get("ext", "")).lower()
    if ext in _TEXT_EXTS:
        # Text doc: single "page" of raw UTF-8 content, no raster. The review
        # text panel fetches this URL and renders the body verbatim.
        if page != 1:
            raise HTTPException(status_code=404, detail="page out of range")
        return FileResponse(
            doc_path(current_ws(), slug, filename),
            media_type="text/plain; charset=utf-8",
            headers={"Cache-Control": _PAGE_CACHE},
        )
    if ext in _IMAGE_MEDIA:
        if page != 1:
            raise HTTPException(status_code=404, detail="page out of range")
        # PNG doc requested as JPEG → transcode (screenshots/photos shrink a
        # lot); a JPG doc is already JPEG, so serve the original either way.
        if jpeg and ext == "png":
            path = await image_doc_as_jpeg(current_ws(), slug, filename)
            return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": _PAGE_CACHE})
        return FileResponse(
            doc_path(current_ws(), slug, filename),
            media_type=_IMAGE_MEDIA[ext],
            headers={"Cache-Control": _PAGE_CACHE},
        )
    try:
        path = await pdf_render_page(current_ws(), slug, filename, page=page, fmt=fmt)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    # Read the media type off the file the renderer actually chose — under
    # `auto` the codec is a per-page decision, so deriving it from the request
    # would mislabel every page that went the other way.
    media = _IMAGE_MEDIA["jpg" if path.suffix.lower() in (".jpg", ".jpeg") else "png"]
    return FileResponse(path, media_type=media, headers={"Cache-Control": _PAGE_CACHE})


@router.delete("/lab/projects/{slug}/docs/by-name/{filename:path}")
async def delete_doc_endpoint(slug: str, filename: str) -> dict:
    """Delete a doc and every artifact keyed off its filename — sidecar meta,
    draft prediction, reviewed JSON, per-experiment predictions — by moving the
    set into one recoverable `_trash/` bundle. Returns 404 if the doc isn't on
    disk so callers can distinguish a real removal from a no-op."""
    safe_slug(slug)
    safe_filename(filename)
    result = await delete_doc(current_ws(), slug, filename)
    if not result["removed"]:
        raise HTTPException(status_code=404, detail="doc_not_found")
    return result


class _RenameDocBody(BaseModel):
    new_filename: str


@router.post("/lab/projects/{slug}/docs/by-name/{filename:path}/rename")
async def rename_doc_endpoint(slug: str, filename: str, body: _RenameDocBody) -> dict:
    """Rename a doc, carrying its sidecar meta, draft prediction, reviewed JSON
    and per-experiment predictions along. HTTP twin of the `rename_doc` tool —
    both exist because a plain `mv` orphans the artifact set (see the tool
    docstring). 400 on an empty / taken name or an extension change."""
    safe_slug(slug)
    safe_filename(filename)
    safe_filename(body.new_filename.strip())
    try:
        return await rename_doc(current_ws(), slug, filename, body.new_filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="doc_not_found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
