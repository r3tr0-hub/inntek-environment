"""Headless label rendering.

Renders any supported job type to a PIL image / PNG bytes **without** a printer
connection, by driving the same ``TSPLPrinter.build_*`` methods the print path
uses. This is the single source of truth for:

  - the web UI label **preview**, and
  - the Homebox **push** endpoint (which must return an ``image/*`` to Homebox).

Because it reuses the printer's build methods, a preview reflects what will
actually be printed (same fonts, layout, auto-fit and 1-bit dithering).
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image

from labeljetty.printer.tspl import JobType, TSPLPrinter


def _printer(width_mm: int, height_mm: int, dpi: int) -> TSPLPrinter:
    """A connection-less printer instance usable only for rendering."""
    return TSPLPrinter(
        connection=None,
        label_width_mm=width_mm,
        label_height_mm=height_mm,
        dpi=dpi,
        dry_run_mode=True,
    )


def render_label_image(
    job_type: JobType,
    params: Optional[Dict[str, Any]] = None,
    *,
    width_mm: int,
    height_mm: int,
    dpi: int,
    input_file_path: Optional[Path] = None,
) -> Image.Image:
    """Render a job to a 1-bit, label-sized PIL image (exactly what would print).

    The label geometry (``width_mm``/``height_mm``/``dpi``) is required — callers
    resolve their own defaults — so this module stays free of any config import.
    """
    params = params or {}
    printer = _printer(width_mm, height_mm, dpi)
    rotate = params.get("rotate", 0)

    if job_type == "png":
        if input_file_path is None:
            raise ValueError("png preview requires an input file")
        img = printer.build_png_image(
            str(input_file_path),
            fit=params.get("fit", "fit"),
            margin_mm=params.get("margin_mm", 0.0),
            rotate=rotate,
        )
    elif job_type == "pdf":
        if input_file_path is None:
            raise ValueError("pdf preview requires an input file")
        img = printer.build_pdf_image(
            str(input_file_path),
            page=params.get("page", 0),
            fit=params.get("fit", "fit"),
            margin_mm=params.get("margin_mm", 0.0),
            rotate=rotate,
        )
    elif job_type == "text":
        img = printer.build_text_image(
            params.get("text", ""),
            font_size=params.get("font_size"),
            fit=params.get("fit", "fill"),
            rotate=rotate,
        )
    elif job_type == "markdown":
        img = printer.build_markdown_image(
            params.get("text", ""), fit=params.get("fit", "fill"), rotate=rotate
        )
    elif job_type == "barcode":
        img = printer.build_barcode_image(
            params.get("data", ""),
            barcode_type=params.get("barcode_type", "128"),
            text=params.get("text"),
        )
    elif job_type == "qrcode":
        if params.get("text"):
            img = printer.build_qrcode_with_text_image(
                params.get("data", ""),
                text=params["text"],
                ecc_level=params.get("ecc_level", "M"),
            )
        else:
            img = printer.build_qrcode_image(
                params.get("data", ""), ecc_level=params.get("ecc_level", "M")
            )
    else:
        raise ValueError(f"Unknown job_type for preview: {job_type}")

    return printer._prepare_1bit(img)


def render_label_png_bytes(
    job_type: JobType,
    params: Optional[Dict[str, Any]] = None,
    *,
    width_mm: int,
    height_mm: int,
    dpi: int,
    input_file_path: Optional[Path] = None,
) -> bytes:
    """Render a job and return PNG-encoded bytes (for HTTP responses)."""
    img = render_label_image(
        job_type,
        params,
        width_mm=width_mm,
        height_mm=height_mm,
        dpi=dpi,
        input_file_path=input_file_path,
    )
    buf = io.BytesIO()
    # Convert 1-bit → for broad browser compatibility keep as PNG (mode "1" is fine).
    img.save(buf, format="PNG")
    return buf.getvalue()
