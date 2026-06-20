import json

from fastapi import APIRouter, Depends, HTTPException
from app.auth.deps import bind_workspace, current_ws
from fastapi.responses import FileResponse

from app.api.routes._safety import safe_filename, safe_slug
from app.config import get_settings
from app.tools.docs import delete_doc, image_doc_as_jpeg, pdf_render_page
from app.workspace.paths import doc_meta_path, doc_path


router = APIRouter(dependencies=[Depends(bind_workspace)])


_IMAGE_MEDIA = {"png": "image/png", "jpg": "image/jpeg"}

# Page rasters are immutable: a doc never changes bytes once uploaded
# (filename is a unique slot, the PDF render cache is content-addressed by
# sha). So the browser can cache a page forever and skip the per-page
# conditional revalidation round-trip on every board reopen / page flip.
_PAGE_CACHE = "public, max-age=31536000, immutable"


@router.get("/lab/projects/{slug}/docs/by-name/{filename:path}/pages/{page}")
async def get_page(slug: str, filename: str, page: int, fmt: str = "png") -> FileResponse:
    """Serve a viewable page bitmap for a doc.

    Filename is the only doc handle (post-d_xxx removal). The `:path` converter
    lets percent-encoded names with spaces or dots through; we still
    defensively validate the result via `safe_filename` to reject path
    separators and traversal segments.

    `fmt=jpeg` serves a JPEG at the SAME resolution (board overview — smaller on
    photo-heavy pages, clarity preserved); `fmt=png` (default) is pixel-exact
    for review.

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
        path = await pdf_render_page(current_ws(), slug, filename, page=page, fmt="jpeg" if jpeg else "png")
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    media = "image/jpeg" if jpeg else "image/png"
    return FileResponse(path, media_type=media, headers={"Cache-Control": _PAGE_CACHE})


@router.delete("/lab/projects/{slug}/docs/by-name/{filename:path}")
async def delete_doc_endpoint(slug: str, filename: str) -> dict:
    """Delete a doc and every artifact keyed off its filename — sidecar meta,
    PDF render cache, draft prediction, reviewed JSON, per-experiment
    predictions. Returns 404 if the doc isn't on disk so callers can
    distinguish a real removal from a no-op."""
    safe_slug(slug)
    safe_filename(filename)
    settings = get_settings()
    result = await delete_doc(current_ws(), slug, filename)
    if not result["removed"]:
        raise HTTPException(status_code=404, detail="doc_not_found")
    return result
