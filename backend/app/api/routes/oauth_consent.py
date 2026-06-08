"""OAuth consent interstitial — the one human step in the P2 login flow.

The SDK ``/authorize`` handler validates the request then calls
``provider.authorize()``, which parks the request as a transaction and redirects
the browser here. This route is emerge-owned so it can see the **session cookie**
(the SDK auth handlers can't): it identifies the resource owner, shows a minimal
"allow this app?" screen, and on approval asks the provider to mint the
authorization code and bounce back to the client's ``redirect_uri``.

Self-contained & server-rendered (no frontend coupling): if the browser isn't
logged into emerge yet, the same page carries an email/password field so the
teammate logs in and approves in one step. Reuses the exact session mechanism as
``/auth/login`` (``request.session["uid"]``), so an already-logged-in operator
just clicks Approve.
"""
from __future__ import annotations

import html

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import store
from app.auth.oauth import get_oauth_provider
from app.config import get_settings

router = APIRouter()


def _page(*, title: str, inner: str, status: int = 200) -> HTMLResponse:
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · emerge</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ margin:0; min-height:100vh; display:grid; place-items:center;
         background:#f4f1ea; color:#26221c;
         font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }}
  .card {{ width:min(380px,92vw); background:#fbf9f4; border:1px solid #e4ddcf;
          border-radius:14px; padding:28px 26px; box-shadow:0 6px 24px rgba(40,34,22,.07); }}
  h1 {{ font-size:17px; margin:0 0 4px; font-weight:650; }}
  .sub {{ color:#7c7363; font-size:13px; margin:0 0 18px; }}
  .grant {{ background:#f1ece0; border:1px solid #e4ddcf; border-radius:10px;
           padding:12px 14px; margin:0 0 18px; font-size:13.5px; }}
  .grant b {{ color:#26221c; }}
  .who {{ color:#7c7363; font-size:12.5px; margin:0 0 16px; }}
  label {{ display:block; font-size:12.5px; color:#7c7363; margin:0 0 4px; }}
  input {{ width:100%; box-sizing:border-box; padding:9px 11px; margin:0 0 13px;
          border:1px solid #d9d1c0; border-radius:8px; background:#fff; font-size:14px; }}
  input:focus {{ outline:2px solid #b8843a55; border-color:#b8843a; }}
  .row {{ display:flex; gap:10px; margin-top:4px; }}
  button {{ flex:1; padding:10px 12px; border-radius:9px; border:1px solid transparent;
           font-size:14px; font-weight:600; cursor:pointer; }}
  .approve {{ background:#b8843a; color:#fff; }}
  .approve:hover {{ background:#a5742f; }}
  .deny {{ background:transparent; color:#7c7363; border-color:#d9d1c0; }}
  .deny:hover {{ background:#efe9dd; }}
  .err {{ background:#f7e7e3; border:1px solid #e6c3ba; color:#9a3b27;
         border-radius:8px; padding:8px 11px; font-size:12.5px; margin:0 0 14px; }}
</style></head><body><div class="card">{inner}</div></body></html>"""
    return HTMLResponse(doc, status_code=status)


def _expired_page() -> HTMLResponse:
    return _page(
        title="Link expired",
        inner='<h1>This authorization link has expired</h1>'
              '<p class="sub">Start the connection again from your Claude client.</p>',
        status=400,
    )


async def _render_consent(request: Request, txn_id: str, *, error: str | None = None) -> HTMLResponse:
    provider = get_oauth_provider()
    txn = await provider.load_txn(txn_id)
    if txn is None:
        return _expired_page()
    root = get_settings().workspace_root
    client = await provider.get_client(txn["client_id"])
    client_name = html.escape(
        (getattr(client, "client_name", None) or "An application") if client else "An application"
    )

    uid = request.session.get("uid")
    user = await store.get_user(root, uid) if uid else None

    err_html = f'<div class="err">{html.escape(error)}</div>' if error else ""
    txn_esc = html.escape(txn_id)

    if user is not None:
        team = await store.get_team(root, user.active_team_id) if user.active_team_id else None
        team_name = html.escape(team.name) if team else "your workspace"
        identity = (
            f'<p class="who">Signed in as <b>{html.escape(user.email)}</b> · '
            f'workspace <b>{team_name}</b></p>'
        )
        login_fields = ""
    else:
        identity = '<p class="who">Sign in to your emerge account to continue.</p>'
        login_fields = (
            '<label>Email</label><input name="email" type="email" autocomplete="username" required>'
            '<label>Password</label><input name="password" type="password" '
            'autocomplete="current-password" required>'
        )

    inner = (
        f'<h1>Connect to emerge</h1>'
        f'<p class="sub">Let this application work in your emerge workspace.</p>'
        f'{err_html}'
        f'<div class="grant"><b>{client_name}</b> is requesting access to your '
        f'projects, documents, and extractions.</div>'
        f'{identity}'
        f'<form method="post" action="/oauth/consent">'
        f'<input type="hidden" name="txn" value="{txn_esc}">'
        f'{login_fields}'
        f'<div class="row">'
        f'<button class="deny" name="action" value="deny" type="submit">Deny</button>'
        f'<button class="approve" name="action" value="approve" type="submit">Allow</button>'
        f'</div></form>'
    )
    return _page(title="Authorize", inner=inner)


@router.get("/oauth/consent")
async def consent_page(request: Request, txn: str) -> HTMLResponse:
    return await _render_consent(request, txn)


@router.post("/oauth/consent")
async def consent_submit(request: Request):
    from app.auth.passwords import verify_password

    form = await request.form()
    txn_id = str(form.get("txn") or "")
    action = str(form.get("action") or "")
    provider = get_oauth_provider()
    root = get_settings().workspace_root

    if await provider.load_txn(txn_id) is None:
        return _expired_page()

    uid = request.session.get("uid")
    user = await store.get_user(root, uid) if uid else None

    # Not logged in yet → authenticate from the submitted credentials first.
    if user is None:
        email = str(form.get("email") or "").strip()
        password = str(form.get("password") or "")
        candidate = await store.get_user_by_email(root, email) if email else None
        if candidate is None or not verify_password(password, candidate.password_hash):
            return await _render_consent(request, txn_id, error="Email or password is incorrect.")
        request.session["uid"] = candidate.id
        user = candidate

    if action == "deny":
        url = await provider.deny_authorization(txn_id)
    else:
        url = await provider.complete_authorization(txn_id, subject=user.id)
    if url is None:
        return _expired_page()
    return RedirectResponse(url, status_code=302)
