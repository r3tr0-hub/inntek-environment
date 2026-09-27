"""Server-rendered web UI (HTMX + Jinja2).

These routes render HTML for humans and live at the application root, beside the
machine-facing JSON API under ``/api``. They reuse the shared service layer
(enqueue helpers, the headless renderer, status queries) so there is no logic
duplication — only presentation. All routes go through the same ``require_access``
auth seam as the API.
"""

from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path
from typing import Annotated, Optional, Union, get_args, get_origin, Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, File
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlmodel import select

from labeljetty.web.auth import require_access, current_principal, verify_password
from labeljetty.web.password import hash_password
from labeljetty.web.api import _enqueue, _store_upload, _job_response
from labeljetty.config import (
    Config,
    get_config,
    reload_config,
    ui_field_meta,
)
from labeljetty.core.db import (
    PrintJob,
    get_session,
    set_setting_overrides,
    clear_setting_overrides,
)
from labeljetty.printer import JobType
from labeljetty.printer.render import render_label_png_bytes
from labeljetty.service.worker import PrintServiceManager
from labeljetty.core.logging import get_logger
from labeljetty.version import get_version

config = get_config()
log = get_logger()

import sys as _sys


def _resource_dir(subdir: str) -> Path:
    """Путь к папке с ресурсами (templates/static) — работает и в обычном
    запуске, и внутри PyInstaller exe (там __file__ указывает в _MEIPASS)."""
    if getattr(_sys, "frozen", False):
        return Path(_sys._MEIPASS) / "labeljetty" / "web" / subdir
    return Path(__file__).parent / subdir


TEMPLATES_DIR = _resource_dir("templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Python 3.14 ужесточил хеширование: ключ кеша Jinja2 (кортеж с dict внутри)
# стал нехешируемым → TypeError. Отключаем кеш шаблонов.
templates.env.cache = None

# Starlette 1.x поменял сигнатуру TemplateResponse:
#   было:  TemplateResponse(name, context)
#   стало: TemplateResponse(request, name, context)
# Оборачиваем метод, чтобы старые вызовы автоматически превращались в новые.
_original_template_response = templates.TemplateResponse


def _compat_template_response(*args, **kwargs):
    if args and isinstance(args[0], str):
        name = args[0]
        context = args[1] if len(args) > 1 and isinstance(args[1], dict) else {}
        rest = args[2:]
        request = context.get("request")
        if request is not None:
            return _original_template_response(request, name, context, *rest, **kwargs)
    return _original_template_response(*args, **kwargs)


templates.TemplateResponse = _compat_template_response

ui_router = APIRouter(include_in_schema=False)

# Job types that carry an uploaded file rather than form parameters.
FILE_JOB_TYPES = {"png", "pdf"}


def _base_context(request: Request) -> dict:
    """Context shared by every template (nav, profiles, feature flags)."""
    return {
        "request": request,
        "app_name": config.APP_NAME,
        "profiles": config.get_label_profiles(),
        "default_width_mm": config.DEFAULT_LABEL_WIDTH_MM,
        "default_height_mm": config.DEFAULT_LABEL_HEIGHT_MM,
        "default_dpi": config.DEFAULT_DPI,
        "homebox_enabled": config.homebox_configured(),
        "auth_enabled": config.auth_enabled(),
        "settings_ui_enabled": config.SETTINGS_UI_ENABLED,
        "principal": current_principal(request),
        "version": get_version(),
    }


def _geometry(
    label_width_mm: Optional[int],
    label_height_mm: Optional[int],
    dpi: Optional[int],
) -> tuple[int, int, int]:
    """Resolve a label geometry, falling back to server defaults."""
    return (
        label_width_mm or config.DEFAULT_LABEL_WIDTH_MM,
        label_height_mm or config.DEFAULT_LABEL_HEIGHT_MM,
        dpi or config.DEFAULT_DPI,
    )


def _build_params(
    job_type: JobType,
    *,
    text: Optional[str],
    data: Optional[str],
    barcode_type: str,
    ecc_level: str,
    font_size: Optional[int],
    fit: str,
    page: str,
    image_fit: str,
    rotate: int = 0,
) -> dict:
    """Assemble the type-specific ``params`` dict from the shared form fields.

    ``rotate`` (0/90/180/270°, clockwise) is carried for the content types that
    support it — text, markdown, PDF and images.
    """
    if job_type == "text":
        return {"text": text or "", "font_size": font_size, "fit": fit, "rotate": rotate}
    if job_type == "markdown":
        return {"text": text or "", "fit": fit, "rotate": rotate}
    if job_type == "barcode":
        return {"data": data or "", "barcode_type": barcode_type, "text": text or None}
    if job_type == "qrcode":
        return {"data": data or "", "ecc_level": ecc_level, "text": text or None}
    if job_type == "pdf":
        return {
            "page": page if page == "all" else int(page or 0),
            "fit": image_fit,
            "rotate": rotate,
        }
    if job_type == "png":
        return {"fit": image_fit, "rotate": rotate}
    return {}


# --------------------------------------------------------------------------- #
#  Login / logout (human auth — these routes are intentionally public)
# --------------------------------------------------------------------------- #
@ui_router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, next: str = "/"):
    # Nothing to log into when auth is off or no local users exist.
    if not config.auth_enabled() or not config.AUTH_USERS:
        return RedirectResponse("/", status_code=303)
    ctx = _base_context(request)
    ctx.update({"next": next, "error": None})
    return templates.TemplateResponse("login.html", ctx)


@ui_router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next: Annotated[str, Form()] = "/",
):
    user = config.find_user(username)
    if user is None or not verify_password(password, user.password_hash):
        ctx = _base_context(request)
        ctx.update({"next": next, "error": "Invalid username or password."})
        return templates.TemplateResponse(
            "login.html", ctx, status_code=401
        )
    request.session["sub"] = user.username
    # Only allow same-site relative redirects to avoid open-redirect abuse.
    target = next if next.startswith("/") and not next.startswith("//") else "/"
    return RedirectResponse(target, status_code=303)


@ui_router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# --------------------------------------------------------------------------- #
#  Pages
# --------------------------------------------------------------------------- #
@ui_router.get("/", response_class=HTMLResponse)
async def index(
    request: Request, access: Annotated[bool, Depends(require_access)]
):
    return templates.TemplateResponse("index.html", _base_context(request))


# --------------------------------------------------------------------------- #
#  Preview (render only — no print)
# --------------------------------------------------------------------------- #
@ui_router.post("/ui/preview", response_class=HTMLResponse)
async def ui_preview(
    request: Request,
    access: Annotated[bool, Depends(require_access)],
    job_type: Annotated[JobType, Form()],
    text: Annotated[Optional[str], Form()] = None,
    data: Annotated[Optional[str], Form()] = None,
    barcode_type: Annotated[str, Form()] = "128",
    ecc_level: Annotated[str, Form()] = "M",
    font_size: Annotated[Optional[int], Form()] = None,
    fit: Annotated[str, Form()] = "fill",
    page: Annotated[str, Form()] = "0",
    image_fit: Annotated[str, Form()] = "fit",
    rotate: Annotated[int, Form()] = 0,
    label_width_mm: Annotated[Optional[int], Form()] = None,
    label_height_mm: Annotated[Optional[int], Form()] = None,
    dpi: Annotated[Optional[int], Form()] = None,
    file: Annotated[Optional[UploadFile], File()] = None,
):
    w, h, d = _geometry(label_width_mm, label_height_mm, dpi)
    params = _build_params(
        job_type,
        text=text,
        data=data,
        barcode_type=barcode_type,
        ecc_level=ecc_level,
        font_size=font_size,
        fit=fit,
        page=page,
        image_fit=image_fit,
        rotate=rotate,
    )

    tmp_path: Optional[Path] = None
    try:
        if job_type in FILE_JOB_TYPES:
            if file is None or not file.filename:
                return templates.TemplateResponse(
                    "_preview.html",
                    {"request": request, "error": "Choose a file to preview."},
                )
            suffix = ".pdf" if job_type == "pdf" else ".png"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(await file.read())
                tmp_path = Path(tmp.name)

        png = render_label_png_bytes(
            job_type,
            params,
            width_mm=w,
            height_mm=h,
            dpi=d,
            input_file_path=tmp_path,
        )
    except Exception as e:  # render errors → show inline, don't 500 the page
        log.warning(f"Preview render failed: {e}")
        return templates.TemplateResponse(
            "_preview.html", {"request": request, "error": str(e)}
        )
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    data_uri = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    return templates.TemplateResponse(
        "_preview.html",
        {"request": request, "image": data_uri, "width_mm": w, "height_mm": h},
    )


# --------------------------------------------------------------------------- #
#  Print (enqueue)
# --------------------------------------------------------------------------- #
@ui_router.post("/ui/print", response_class=HTMLResponse)
async def ui_print(
    request: Request,
    access: Annotated[bool, Depends(require_access)],
    job_type: Annotated[JobType, Form()],
    text: Annotated[Optional[str], Form()] = None,
    data: Annotated[Optional[str], Form()] = None,
    barcode_type: Annotated[str, Form()] = "128",
    ecc_level: Annotated[str, Form()] = "M",
    font_size: Annotated[Optional[int], Form()] = None,
    fit: Annotated[str, Form()] = "fill",
    page: Annotated[str, Form()] = "0",
    image_fit: Annotated[str, Form()] = "fit",
    rotate: Annotated[int, Form()] = 0,
    label_width_mm: Annotated[Optional[int], Form()] = None,
    label_height_mm: Annotated[Optional[int], Form()] = None,
    dpi: Annotated[Optional[int], Form()] = None,
    copies: Annotated[int, Form()] = 1,
    file: Annotated[Optional[UploadFile], File()] = None,
):
    from labeljetty.web.api import LabelOptions

    opts = LabelOptions(
        label_width_mm=label_width_mm,
        label_height_mm=label_height_mm,
        dpi=dpi,
        copies=copies,
    )
    params = _build_params(
        job_type,
        text=text,
        data=data,
        barcode_type=barcode_type,
        ecc_level=ecc_level,
        font_size=font_size,
        fit=fit,
        page=page,
        image_fit=image_fit,
        rotate=rotate,
    )
    try:
        input_file_name = None
        if job_type in FILE_JOB_TYPES:
            if file is None or not file.filename:
                raise ValueError("Choose a file to print.")
            input_file_name = _store_upload(
                file, ".pdf" if job_type == "pdf" else ".png"
            )
        job = _enqueue(
            job_type, opts=opts, params=params, input_file_name=input_file_name
        )
    except Exception as e:
        log.warning(f"Enqueue from UI failed: {e}")
        return templates.TemplateResponse(
            "_print_result.html", {"request": request, "error": str(e)}
        )

    # Tell the job list to refresh immediately.
    resp = templates.TemplateResponse(
        "_print_result.html", {"request": request, "job": job}
    )
    resp.headers["HX-Trigger"] = "jobsChanged"
    return resp


# --------------------------------------------------------------------------- #
#  Polled fragments: job list + status
# --------------------------------------------------------------------------- #
@ui_router.get("/ui/jobs", response_class=HTMLResponse)
async def ui_jobs(
    request: Request,
    access: Annotated[bool, Depends(require_access)],
    limit: int = 20,
):
    with get_session() as session:
        stmt = select(PrintJob).order_by(PrintJob.created_at.desc()).limit(limit)
        jobs = [_job_response(j) for j in session.exec(stmt).all()]
    return templates.TemplateResponse(
        "_jobs.html", {"request": request, "jobs": jobs}
    )


@ui_router.get("/ui/homebox", response_class=HTMLResponse)
async def ui_homebox(
    request: Request, access: Annotated[bool, Depends(require_access)]
):
    if not config.homebox_configured():
        return HTMLResponse("")  # module disabled → render nothing
    ctx = _base_context(request)
    ctx["homebox_url"] = config.HOMEBOX_URL
    return templates.TemplateResponse("_homebox.html", ctx)


@ui_router.get("/ui/homebox/search", response_class=HTMLResponse)
def ui_homebox_search(
    request: Request,
    access: Annotated[bool, Depends(require_access)],
    q: str = "",
    is_location: bool = False,
):
    """Sync route (threadpool) — performs a blocking Homebox API call."""
    if not config.homebox_configured():
        return HTMLResponse("")
    from labeljetty.integrations.homebox import HomeboxClient, HomeboxError

    if not q.strip():
        return templates.TemplateResponse(
            "_homebox_results.html", {"request": request, "results": []}
        )
    try:
        client = HomeboxClient()
        entities = client.search(q, is_location=is_location)
        results = [
            {"entity": e, "web_url": client.entity_web_url(e.id)} for e in entities
        ]
    except HomeboxError as e:
        return templates.TemplateResponse(
            "_homebox_results.html", {"request": request, "error": str(e)}
        )
    return templates.TemplateResponse(
        "_homebox_results.html", {"request": request, "results": results}
    )


def _homebox_fetch_label(kind: str, entity_id: str) -> tuple[bytes, str]:
    """Fetch Homebox's own label image; returns (bytes, file-suffix)."""
    from labeljetty.integrations.homebox import HomeboxClient

    client = HomeboxClient()
    data, content_type = client.fetch_label(kind, entity_id)
    suffix = ".pdf" if "pdf" in content_type.lower() or data[:4] == b"%PDF" else ".png"
    return data, suffix


@ui_router.post("/ui/homebox/preview", response_class=HTMLResponse)
def ui_homebox_preview(
    request: Request,
    access: Annotated[bool, Depends(require_access)],
    kind: str = Form(...),
    entity_id: str = Form(...),
):
    """Preview Homebox's own label (fetched from its labelmaker API)."""
    from labeljetty.integrations.homebox import HomeboxError

    if not config.homebox_configured():
        return HTMLResponse("")
    try:
        data, suffix = _homebox_fetch_label(kind, entity_id)
    except HomeboxError as e:
        return templates.TemplateResponse(
            "_preview.html", {"request": request, "error": str(e)}
        )
    # Render through our own pipeline so the preview reflects exactly what prints —
    # including the Homebox safety border (HOMEBOX_LABEL_MARGIN_MM) inset.
    import tempfile
    from labeljetty.printer.render import render_label_png_bytes

    w, h, d = _geometry(None, None, None)
    job_type = "pdf" if suffix == ".pdf" else "png"
    params: dict = {"margin_mm": config.HOMEBOX_LABEL_MARGIN_MM}
    if job_type == "pdf":
        params["page"] = 0
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        data = render_label_png_bytes(
            job_type, params, width_mm=w, height_mm=h, dpi=d, input_file_path=tmp_path
        )
    finally:
        tmp_path.unlink(missing_ok=True)
    data_uri = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
    return templates.TemplateResponse(
        "_preview.html", {"request": request, "image": data_uri, "homebox": True}
    )


@ui_router.post("/ui/homebox/print", response_class=HTMLResponse)
def ui_homebox_print(
    request: Request,
    access: Annotated[bool, Depends(require_access)],
    kind: str = Form(...),
    entity_id: str = Form(...),
):
    """Print Homebox's own label: fetch it from the labelmaker API and enqueue."""
    from labeljetty.integrations.homebox import HomeboxError
    from labeljetty.web.api import _store_bytes

    if not config.homebox_configured():
        return HTMLResponse("")
    try:
        data, suffix = _homebox_fetch_label(kind, entity_id)
        filename = _store_bytes(data, suffix)
        job_type = "pdf" if suffix == ".pdf" else "png"
        params = {"margin_mm": config.HOMEBOX_LABEL_MARGIN_MM}
        if job_type == "pdf":
            params["page"] = 0
        job = _enqueue(job_type, params=params, input_file_name=filename)
    except (HomeboxError, Exception) as e:
        return templates.TemplateResponse(
            "_print_result.html", {"request": request, "error": str(e)}
        )
    resp = templates.TemplateResponse(
        "_print_result.html", {"request": request, "job": job}
    )
    resp.headers["HX-Trigger"] = "jobsChanged"
    return resp


@ui_router.get("/ui/homebox/setup", response_class=HTMLResponse)
async def ui_homebox_setup(
    request: Request,
    access: Annotated[bool, Depends(require_access)],
    host: Optional[str] = None,
):
    """Setup-helper page: generate the Homebox print-command script + env hints.

    ``host`` lets the user enter the printer service's address as reachable *from
    the Homebox host* (the page's own URL is often localhost/127.0.0.1 and useless
    in the generated script).
    """
    if host:
        base = host.strip().rstrip("/")
        if not base.startswith(("http://", "https://")):
            base = "http://" + base
    else:
        base = str(request.base_url).rstrip("/")
    w_mm, h_mm = config.DEFAULT_LABEL_WIDTH_MM, config.DEFAULT_LABEL_HEIGHT_MM
    dpi = config.DEFAULT_DPI
    width_px = round(w_mm / 25.4 * dpi)
    height_px = round(h_mm / 25.4 * dpi)

    # If protected, embed the first configured API token in the generated script.
    token = config.AUTH_TOKENS[0].token if config.AUTH_TOKENS else None
    auth_line = f'  -H "Authorization: Bearer {token}" \\\n' if token else ""
    print_script = (
        "#!/usr/bin/env sh\n"
        "# HBOX_LABEL_MAKER_PRINT_COMMAND = /path/to/this-script.sh {{.FileName}}\n"
        f'curl -fsS -X POST "{base}/api/print/png" \\\n'
        f"{auth_line}"
        '  -F "file=@$1"\n'
    )

    ctx = _base_context(request)
    ctx.update(
        {
            "label_service_url": f"{base}/api/homebox/label",
            "print_script": print_script,
            "autoprint": config.HOMEBOX_LABEL_SERVICE_AUTOPRINT,
            "width_px": width_px,
            "height_px": height_px,
            "padding_px": max(2, width_px // 20),
            "font_size_px": max(8, height_px // 6),
            "w_mm": w_mm,
            "h_mm": h_mm,
            "dpi": dpi,
            "host_value": host or "",
            "base": base,
        }
    )
    return templates.TemplateResponse("homebox_setup.html", ctx)


@ui_router.get("/ui/update", response_class=HTMLResponse)
def ui_update(
    request: Request, access: Annotated[bool, Depends(require_access)]
):
    """Update-available banner fragment — empty unless a newer release exists.

    Sync route (threadpool): check_for_update() may do a blocking GitHub call on
    a cache miss. Loaded once per page via hx-trigger="load" from base.html."""
    from labeljetty.update import check_for_update

    info = check_for_update()
    if not info.update_available:
        return HTMLResponse("")  # nothing to show → render nothing
    return templates.TemplateResponse(
        "_update.html",
        {"request": request, "update": info, "repo": config.UPDATE_CHECK_REPO},
    )


@ui_router.get("/ui/status", response_class=HTMLResponse)
async def ui_status(
    request: Request, access: Annotated[bool, Depends(require_access)]
):
    worker = PrintServiceManager.get_worker_status()

    printer_reachable = False
    printer_status = None
    printer_supported = False
    printer_error = None
    printer_info = None
    con = None
    try:
        from labeljetty.printer import TSPLPrinter

        con = config.get_printer_connection()
        # USB facts don't need the device claimed, so gather them first — they
        # stay available even if the connect() below fails (e.g. busy worker).
        printer_info = con.info()
        # Fail fast and always release — see disconnect() / printer_status notes.
        con.connect(max_retries=1)
        printer = TSPLPrinter(
            connection=con,
            label_width_mm=config.DEFAULT_LABEL_WIDTH_MM,
            label_height_mm=config.DEFAULT_LABEL_HEIGHT_MM,
            dpi=config.DEFAULT_DPI,
        )
        msg = printer.get_status()
        printer_reachable = True
        printer_supported = msg is not None
        printer_status = msg
    except Exception as e:
        printer_error = str(e)
    finally:
        if con is not None:
            con.disconnect()

    return templates.TemplateResponse(
        "_status.html",
        {
            "request": request,
            "worker": worker,
            "printer_reachable": printer_reachable,
            "printer_supported": printer_supported,
            "printer_status": printer_status,
            "printer_error": printer_error,
            "printer_info": printer_info,
            "autodetected": not config.PRINTER_USB,
        },
    )


# --------------------------------------------------------------------------- #
#  Settings (admin config page — generic form built from Config.model_fields)
# --------------------------------------------------------------------------- #
# Read-only fields shown for context (infra tier — not editable from the web).
_SYSTEM_INFO_FIELDS = [
    ("Listening host", "SERVER_LISTENING_HOST"),
    ("Listening port", "SERVER_LISTENING_PORT"),
    ("Database path", "SQLITE_PATH"),
    ("Image storage", "IMAGE_STORAGE_DIRECTORY"),
    ("Auth mode", "AUTH_MODE"),
]
# Render groups in a stable, sensible order; unknown groups fall to the end.
_GROUP_ORDER = [
    "Label defaults",
    "Printer",
    "Authentication",
    "Homebox",
    "Maintenance",
    "System",
]


def _usb_candidates() -> list[dict]:
    """All connected USB devices (printer-like ones flagged) for the picker, or
    [] if USB can't be enumerated. Lazy import so the page never hard-depends on
    libusb being importable."""
    try:
        from labeljetty.printer.connection import TSPLPrinterConnectionUSB

        return TSPLPrinterConnectionUSB.list_usb_devices()
    except Exception as e:  # pragma: no cover - depends on host USB stack
        log.warning(f"USB device enumeration failed: {e}")
        return []


def _unwrap_optional(annotation):
    """Return (inner_annotation, is_optional) — strips ``Optional[...]``."""
    if get_origin(annotation) is Union:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
    return annotation, False


def _field_widget(name: str, ui: dict) -> tuple[str, list]:
    """Pick an input widget for a field: explicit ``ui['widget']`` wins, else infer
    from the annotation (bool→checkbox, Literal→select, int→number, else text)."""
    if ui.get("widget"):
        return ui["widget"], []
    ann, _ = _unwrap_optional(Config.model_fields[name].annotation)
    if ann is bool:
        return "checkbox", []
    if get_origin(ann) is Literal:
        return "select", list(get_args(ann))
    if ann is int:
        return "number", []
    return "text", []


def _settings_field_views(cfg: Config) -> dict:
    """Build grouped view-models for the editable fields, in display order."""
    meta = ui_field_meta()
    locked = set(cfg.SETTINGS_LOCKED_KEYS)
    groups: dict[str, list] = {}
    for name, ui in meta.items():
        field = Config.model_fields[name]
        widget, options = _field_widget(name, ui)
        value = getattr(cfg, name)
        view = {
            "name": name,
            "label": ui.get("label") or name,
            "help": field.description,
            "widget": widget,
            "options": options,
            "locked": name in locked,
            "restart": ui.get("restart", False),
            "checked": bool(value) if widget == "checkbox" else False,
            "value": "" if value is None else value,
            "json_text": json.dumps(jsonable_encoder(value), indent=2)
            if widget in ("json", "label_profiles")
            else "",
        }
        # Read-only string shown when a complex field is locked via env.
        view["locked_display"] = "" if value is None else str(value)
        if widget == "label_profiles":
            # Structured rows for the friendly table editor.
            view["rows"] = [jsonable_encoder(p) for p in value]
            view["locked_display"] = view["json_text"]
        elif widget == "printer_select":
            candidates = _usb_candidates()
            current = "" if value is None else str(value)
            view["candidates"] = candidates
            # "custom" = a pinned selector not in the picker (serial:/port:/bus:…
            # or a device that isn't currently plugged in).
            view["is_custom"] = bool(current) and current not in {
                c["selector"] for c in candidates
            }
        elif widget == "auth_users":
            # Usernames only — password hashes are never sent to the browser.
            view["users"] = [{"username": u.username} for u in value]
            view["locked_display"] = ", ".join(u.username for u in value)
        groups.setdefault(ui.get("group", "Other"), []).append(view)
    ordered = {g: groups[g] for g in _GROUP_ORDER if g in groups}
    for g in groups:  # any group not in the explicit order, appended
        ordered.setdefault(g, groups[g])
    return ordered


def _group_notes(cfg: Config) -> dict:
    """Per-group explanatory notes shown under the group heading."""
    homebox = (
        "The Homebox API key is a <strong>secret</strong> and is set only via the "
        "<code>HOMEBOX_API_KEY</code> environment variable — it cannot be edited here. "
    )
    homebox += (
        "It is currently set. ✓"
        if cfg.HOMEBOX_API_KEY
        else "It is <strong>not set</strong>, so the Homebox module stays disabled until you set it in the environment. ⚠"
    )

    auth = (
        "Add a login user and switch <em>Authentication mode</em> to <code>protected</code> to "
        "secure the interface — no need to edit env/compose. Passwords are stored hashed; leave a "
        "user's password blank to keep it unchanged. "
    )
    if not cfg.SESSION_SECRET:
        auth += (
            "<strong>Note:</strong> <code>SESSION_SECRET</code> is unset, so logins won't survive "
            "a restart — set it in the environment for stable sessions. "
        )
    auth += (
        "API tokens (<code>AUTH_TOKENS</code>) remain environment-only. Make sure you can log in "
        "before saving <code>protected</code> — a mismatch would lock out the UI."
    )
    return {"Homebox": homebox, "Authentication": auth}


def _settings_context(request: Request, **extra) -> dict:
    cfg = get_config()
    ctx = _base_context(request)
    ctx.update(
        {
            "groups": _settings_field_views(cfg),
            "group_notes": _group_notes(cfg),
            "system_info": [
                (label, getattr(cfg, attr)) for label, attr in _SYSTEM_INFO_FIELDS
            ],
            "open_mode_warning": not cfg.auth_enabled(),
            "error": None,
            "saved": False,
            "restart_pending": False,
        }
    )
    ctx.update(extra)
    return ctx


def _require_settings_ui() -> None:
    """404 when the settings UI is disabled (default), so it's invisible unless
    deliberately switched on with SETTINGS_UI_ENABLED."""
    if not get_config().SETTINGS_UI_ENABLED:
        raise HTTPException(status_code=404)


@ui_router.get("/ui/settings", response_class=HTMLResponse)
async def ui_settings(
    request: Request, access: Annotated[bool, Depends(require_access)]
):
    _require_settings_ui()
    return templates.TemplateResponse("settings.html", _settings_context(request))


@ui_router.post("/ui/settings", response_class=HTMLResponse)
async def ui_settings_save(
    request: Request, access: Annotated[bool, Depends(require_access)]
):
    _require_settings_ui()
    form = await request.form()
    cfg = get_config()
    meta = ui_field_meta()
    locked = set(cfg.SETTINGS_LOCKED_KEYS)

    overrides: dict = {}
    field_errors: list[str] = []
    restart_pending = False
    for name, ui in meta.items():
        if name in locked:
            continue
        field = Config.model_fields[name]
        widget, _ = _field_widget(name, ui)
        if ui.get("restart"):
            restart_pending = True
        if widget == "checkbox":
            overrides[name] = name in form
        elif widget == "label_profiles":
            # Parallel-array row editor: lp_name[]/lp_width[]/lp_height[]/lp_dpi[].
            names = form.getlist("lp_name")
            widths = form.getlist("lp_width")
            heights = form.getlist("lp_height")
            dpis = form.getlist("lp_dpi")
            profiles = []
            for i, pname in enumerate(names):
                pname = pname.strip()
                if not pname:
                    continue  # blank row → ignore
                w = (widths[i] if i < len(widths) else "").strip()
                h = (heights[i] if i < len(heights) else "").strip()
                d = (dpis[i] if i < len(dpis) else "").strip()
                if not w or not h:
                    field_errors.append(f"Label profile '{pname}': width and height are required")
                    continue
                row = {"name": pname, "width_mm": w, "height_mm": h}
                if d:
                    row["dpi"] = d
                profiles.append(row)  # ints validated by the model below
            overrides[name] = profiles
        elif widget == "printer_select":
            choice = str(form.get("PRINTER_USB_choice", "")).strip()
            if choice == "__custom__":
                choice = str(form.get("PRINTER_USB_custom", "")).strip()
            overrides[name] = choice or None
        elif widget == "auth_users":
            # Row editor: au_username[]/au_password[]. A blank password keeps the
            # existing user's hash; a new user without a password is an error. Only
            # password *hashes* are ever stored — plaintext is hashed here and dropped.
            usernames = form.getlist("au_username")
            passwords = form.getlist("au_password")
            users = []
            for i, uname in enumerate(usernames):
                uname = uname.strip()
                if not uname:
                    continue  # blank row → ignore (also how you remove a user)
                pw = (passwords[i] if i < len(passwords) else "").strip()
                if pw:
                    users.append({"username": uname, "password_hash": hash_password(pw)})
                else:
                    existing = cfg.find_user(uname)
                    if existing is None:
                        field_errors.append(f"User '{uname}': set a password for a new user")
                    else:
                        users.append(
                            {"username": uname, "password_hash": existing.password_hash}
                        )
            overrides[name] = users
        elif widget == "json":
            raw = str(form.get(name, "")).strip()
            try:
                overrides[name] = json.loads(raw) if raw else []
            except json.JSONDecodeError as e:
                field_errors.append(f"{ui.get('label') or name}: invalid JSON ({e})")
        elif widget == "number":
            raw = str(form.get(name, "")).strip()
            if raw == "":
                continue  # leave to env/default
            try:
                overrides[name] = int(raw)
            except ValueError:
                field_errors.append(f"{ui.get('label') or name}: must be a number")
        else:  # text / select
            if name not in form:
                continue
            raw = str(form.get(name)).strip()
            _, optional = _unwrap_optional(field.annotation)
            overrides[name] = None if (optional and raw == "") else raw

    if field_errors:
        return templates.TemplateResponse(
            "settings.html",
            _settings_context(request, error=" • ".join(field_errors)),
            status_code=400,
        )

    # Validate the whole config with the overlay applied — reuses model validators
    # (e.g. the auth lock-out guard) so a bad edit is rejected, not persisted.
    try:
        Config(**overrides)
    except ValidationError as e:
        msg = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()
        )
        return templates.TemplateResponse(
            "settings.html",
            _settings_context(request, error=msg),
            status_code=400,
        )

    set_setting_overrides({k: json.dumps(jsonable_encoder(v)) for k, v in overrides.items()})
    reload_config()
    log.info(f"Settings updated via UI: {sorted(overrides)}")
    return templates.TemplateResponse(
        "settings.html",
        _settings_context(request, saved=True, restart_pending=restart_pending),
    )


@ui_router.post("/ui/settings/reset", response_class=HTMLResponse)
async def ui_settings_reset(
    request: Request, access: Annotated[bool, Depends(require_access)]
):
    _require_settings_ui()
    clear_setting_overrides()
    reload_config()
    log.info("Settings overrides cleared via UI — reverted to env/defaults")
    return templates.TemplateResponse(
        "settings.html", _settings_context(request, saved=True)
    )
