#!/usr/bin/env python3
from typing import List, Optional, Union, IO, Literal
from PIL import Image, ImageDraw, ImageFont, _typing
from labeljetty.printer.connection import TSPLPrinterConnectionUSB

from pydantic import BaseModel

import sys

if sys.platform == "win32":
    DEFAULT_FONT_PATH = "C:/Windows/Fonts/arialbd.ttf"
else:
    DEFAULT_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# The set of renderer kinds the library/service can produce. Lives here (the
# library) rather than in the persistence layer so the printer package stays
# free of any internal dependency.
JobType = Literal["png", "pdf", "text", "markdown", "barcode", "qrcode", "raw"]


class TSPLPrinterStatusMessage(BaseModel):
    """Decoded printer status, parsed from the single byte returned by the TSPL
    real-time status query ``<ESC>!?`` (0x1B 0x21 0x3F).

    Byte map (per the TSPL/TSPL2 programming manual):
        0x00 normal/ready, 0x01 head opened, 0x02 paper jam, 0x04 out of paper,
        0x08 out of ribbon, 0x10 pause, 0x20 printing, 0x80 other error.
    These are combinable bit flags (e.g. 0x05 = out of paper + head opened).
    """

    ready: bool
    head_opened: bool
    paper_jam: bool
    paper_empty: bool
    ribbon_empty: bool
    paused: bool
    printing: bool
    other_error: bool
    raw_status_byte: int

    @property
    def error(self) -> bool:
        """True if the printer reports a fault that blocks printing."""
        return (
            self.head_opened
            or self.paper_jam
            or self.paper_empty
            or self.ribbon_empty
            or self.other_error
        )

    @classmethod
    def from_raw_response(cls, response: int | bytes):
        # Parse status
        if isinstance(response, bytes):
            status_byte: int = int(response[0])
        else:
            status_byte: int = response

        return cls(
            ready=(status_byte == 0),
            head_opened=bool(status_byte & 0x01),
            paper_jam=bool(status_byte & 0x02),
            paper_empty=bool(status_byte & 0x04),
            ribbon_empty=bool(status_byte & 0x08),
            paused=bool(status_byte & 0x10),
            printing=bool(status_byte & 0x20),
            other_error=bool(status_byte & 0x80),
            raw_status_byte=status_byte,
        )


class TSPLPrinter:
    """
    Minimal TSPL printer interface.
    Supports:
      - PNG printing (auto resize)
      - Basic markdown printing
      - FORMFEED (advance to next label)
    """

    def __init__(
        self,
        connection: Union[TSPLPrinterConnectionUSB, None],
        label_width_mm: int = 100,
        label_height_mm: int = 30,
        dpi: int = 203,
        dry_run_mode: bool = False,
    ):
        """_summary_

        Args:
            width_mm (int, optional): _description_. Defaults to 40.
            height_mm (int, optional): _description_. Defaults to 30.
            dpi (int, optional): _description_. Defaults to 203.
            connection (TSPLPrinterConnection | bool, optional): Set a known `usb.core.Device` connection for a specific printer or True if oyu want to auto connect to the first device we can find or false if you want to use `list_available_printers`.`set_printer`. Defaults to False.
            dry_run_mode (bool, optional): _description_. Defaults to False.
        """

        self.connection: TSPLPrinterConnectionUSB = connection
        self.width_mm = label_width_mm
        self.height_mm = label_height_mm
        self.dpi = dpi
        self.dry_run_mode: bool = dry_run_mode

        # Compute pixel size of the label
        self.width_px = int((label_width_mm / 25.4) * dpi)
        self.height_px = int((label_height_mm / 25.4) * dpi)

    # ------------------------------------------------------------ #
    #  Low-level send function
    # ------------------------------------------------------------ #
    def _send(self, data: str | bytes):
        if self.dry_run_mode:
            print(data)
            return
        self.connection.send(data)

    def _send_many(self, data: Union[List[str], tuple[str, ...]]):
        if self.dry_run_mode:
            print(data)
            return
        self.connection.send_many(data)

    # ------------------------------------------------------------ #
    #  Basic TSPL commands
    # ------------------------------------------------------------ #

    def formfeed(self):
        """Advance to the next label."""
        self._send("FORMFEED\n")

    def cls(self):
        """Clear image buffer."""
        self._send("CLS\n")

    def print_label(self, copies=1):
        """Print out current buffered image."""
        self._send(f"PRINT {copies}\n")

    def set_reference_point(self, x: int = 0, y: int = 0):
        """
        Set the reference point (origin) for label printing.

        Args:
            x: X-axis reference point in dots (default: 0)
            y: Y-axis reference point in dots (default: 0)

        By default, many printers center content. Setting this to 0,0
        will align content to the top-left corner of the label.
        """
        self._send(f"REFERENCE {x},{y}\n")

    def set_shift(self, dots: int = 0):
        """
        Set vertical shift of the print position.

        Args:
            dots: Negative values move content up, positive moves down
        """
        self._send(f"SHIFT {dots}\n")

    def set_direction(self, direction: int = 0):
        """
        Set print direction.
        0 = no mirror, 1 = mirror
        """
        self._send(f"DIRECTION {direction}\n")

    def get_status(self) -> Optional[TSPLPrinterStatusMessage]:
        """
        Query the live printer status via the TSPL real-time command
        <ESC>!? (0x1B 0x21 0x3F), which returns a single status byte.

        Returns ``None`` when the printer does not answer. Many cheap TSPL
        clones have an effectively write-only USB interface and never reply to
        status queries — callers must treat ``None`` as "status unavailable"
        rather than an error, so printing is never blocked by an unreadable
        status (see ``is_ready``).
        """
        if self.dry_run_mode:
            return TSPLPrinterStatusMessage.from_raw_response(0)

        # Must be sent raw (no trailing newline).
        response = self.connection.query(b"\x1b!?", raw=True)

        if not response:
            return None
        return TSPLPrinterStatusMessage.from_raw_response(response=response)

    def is_ready(self) -> bool:
        """
        Check if the printer is ready to accept new print jobs.

        If the printer does not report status at all (``get_status`` is
        ``None``), we cannot know — assume ready so printing isn't blocked.
        """
        status = self.get_status()
        if status is None:
            return True
        return status.ready and not status.error

    def wait_until_ready(self, timeout: float = 30, poll_interval: float = 0.5) -> bool:
        """
        Wait until printer is ready.

        Args:
            timeout: Maximum time to wait in seconds
            poll_interval: Time between status checks in seconds

        Returns:
            bool: True if printer became ready, False if timeout
        """
        import time

        start_time = time.time()

        while time.time() - start_time < timeout:
            if self.is_ready():
                return True
            time.sleep(poll_interval)

        return False

    def get_error_message(self) -> str | None:
        """
        Get human-readable error message based on current status.

        Returns:
            str: Error message or None if the printer is okay or still printing.
        """
        status = self.get_status()

        if status is None:
            return None
        # ``printing`` is a normal transient state right after we send PRINT —
        # not an error. Without this check, every successfully-printed label
        # would be marked as failed with the misleading "Printer not ready".
        if status.printing:
            return None
        if status.ready and not status.error:
            return None

        errors: List[str] = []
        if status.head_opened:
            errors.append("Print head open")
        if status.paper_jam:
            errors.append("Paper jam detected")
        if status.paper_empty:
            errors.append("Paper/label out")
        if status.ribbon_empty:
            errors.append("Ribbon out")
        if status.paused:
            errors.append("Printer paused")
        if status.other_error and not errors:
            errors.append("Unknown error")
        if not status.ready and not errors:
            errors.append("Printer not ready")

        return "; ".join(errors) if errors else None

    # ------------------------------------------------------------ #
    # Convert PIL image → TSPL BITMAP command
    # ------------------------------------------------------------ #

    def _bitmap_tspl(self, img: Image.Image, x=0, y=0):
        """
        Convert a 1-bit Pillow image into TSPL BITMAP command bytes.
        """
        if img.mode != "1":
            raise ValueError("Image must be 1-bit monochrome")

        w, h = img.size
        width_bytes = w // 8
        pixels = img.tobytes()

        # TSPL BITMAP uses one byte per 8 pixels, MSB first
        header = f"BITMAP {x},{y},{width_bytes},{h},0,".encode("ascii")
        return header + pixels + b"\n"

    def _set_size(self):
        """Send the SIZE command for the configured label dimensions."""
        self._send(f"SIZE {self.width_mm} mm,{self.height_mm} mm\n")

    def _prepare_1bit(self, img: Image.Image) -> Image.Image:
        """Dither an image to 1-bit and pad its width to a multiple of 8.

        This is exactly what is sent to the printer: Floyd–Steinberg dithering for
        thermal output, then width padded to a multiple of 8 (required by TSPL
        BITMAP). Shared by the print pipeline and the headless preview renderer so
        a preview shows what will actually print.
        """
        # Grayscale, then Floyd–Steinberg dither for thermal output
        if img.mode != "1":
            img = img.convert("L").convert("1", dither=Image.Dither.FLOYDSTEINBERG)

        # Ensure image width is a multiple of 8 (required for TSPL BITMAP)
        if img.width % 8 != 0:
            new_width = ((img.width + 7) // 8) * 8
            padded = Image.new("1", (new_width, img.height), 1)  # 1 = white
            padded.paste(img, (0, 0))
            img = padded
        return img

    def _compose_on_canvas(
        self, img: Image.Image, x: int = 0, y: int = 0
    ) -> Image.Image:
        """Paste ``img`` onto a full white label-sized canvas at ``(x, y)``.

        Used so that a rendered preview always represents the whole label, even
        when the source image (a resized PNG/PDF page, a barcode) is smaller than
        the label.
        """
        canvas = Image.new("L", (self.width_px, self.height_px), 255)
        canvas.paste(img.convert("L"), (x, y))
        return canvas

    def _fit_image(
        self, img: Image.Image, fit: str = "fit", margin_mm: float = 0.0
    ) -> Image.Image:
        """Scale ``img`` onto a full label canvas according to ``fit``.

        Modes (preserving aspect ratio except ``stretch``):
          - ``fit``      contain — scale so the whole image fits inside the label
                         (scales small images *up* too), centered, may leave margins.
          - ``fill``     cover — scale to cover the whole label, centered, overflow
                         cropped (no margins).
          - ``stretch``  resize to the exact label size, ignoring aspect ratio.
          - ``original`` keep the image's own pixel size, centered (cropped if larger).

        ``margin_mm`` reserves a blank safety border (all four sides) by fitting
        into the label *minus* that margin. It is a safe inset used e.g. for
        Homebox labels whose own content sits too close to the edge; the image is
        still centered on the full label canvas.
        """
        canvas = Image.new("L", (self.width_px, self.height_px), 255)
        img = img.convert("L")
        iw, ih = img.size
        margin_px = max(0, round((margin_mm / 25.4) * self.dpi)) if margin_mm else 0
        # Clamp so a too-large margin can never collapse the usable area to <1px.
        margin_px = min(margin_px, (self.width_px - 1) // 2, (self.height_px - 1) // 2)
        lw, lh = self.width_px - 2 * margin_px, self.height_px - 2 * margin_px

        if fit == "original":
            scaled = img
        elif fit == "stretch":
            scaled = img.resize((lw, lh), Image.Resampling.LANCZOS)
        else:
            ratio = (max if fit == "fill" else min)(lw / iw, lh / ih)
            scaled = img.resize(
                (max(1, round(iw * ratio)), max(1, round(ih * ratio))),
                Image.Resampling.LANCZOS,
            )

        # Compose onto an inset sub-canvas first so the safety border always holds:
        # ``fill``/``original`` overflow is cropped *to the inset area*, never bleeding
        # into the margin band. With margin_px == 0 this is just the full canvas.
        inset = Image.new("L", (lw, lh), 255)
        inset.paste(scaled, ((lw - scaled.width) // 2, (lh - scaled.height) // 2))
        canvas.paste(inset, (margin_px, margin_px))
        return canvas

    def _apply_rotation(self, build_fn, rotate: int) -> Image.Image:
        """Build a label image under an optionally-rotated geometry, then rotate
        the finished bitmap back onto the real label.

        ``rotate`` is a clockwise angle in degrees, snapped to 0/90/180/270 (any
        other value is treated as 0). For 90°/270° the label geometry is
        transposed (width ↔ height, in both mm and px) *while* ``build_fn`` runs,
        so auto-fit — text sizing, image scaling — targets the rotated aspect
        ratio; the result is then rotated to land back on the real label. 180°
        needs no swap, just a flip. ``build_fn`` takes no arguments and returns a
        full label-sized PIL image.

        Rotation direction matches the printer's ``BARCODE``/QR convention
        (``rotate=90`` turns the content a quarter-turn clockwise).
        """
        rotate = int(rotate or 0) % 360
        if rotate not in (90, 180, 270):
            return build_fn()

        swap = rotate in (90, 270)
        if swap:
            self.width_mm, self.height_mm = self.height_mm, self.width_mm
            self.width_px, self.height_px = self.height_px, self.width_px
        try:
            img = build_fn()
        finally:
            if swap:
                self.width_mm, self.height_mm = self.height_mm, self.width_mm
                self.width_px, self.height_px = self.height_px, self.width_px

        # Negative angle = clockwise in PIL; expand keeps the exact transposed
        # size (a 90° multiple never introduces gaps to fill).
        return img.rotate(-rotate, expand=True)

    def _render_and_print_image(
        self, img: Image.Image, x: int = 0, y: int = 0, copies: int = 1
    ):
        """
        Shared pipeline: take any PIL image, dither it to 1-bit, pad its width to
        a multiple of 8 (required by TSPL BITMAP), and emit a full label job
        (SIZE → CLS → BITMAP → PRINT). Reused by every image-based print method.
        """
        img = self._prepare_1bit(img)
        self._set_size()
        self.cls()
        self._send(self._bitmap_tspl(img, x, y))
        self.print_label(copies=copies)

    # ------------------------------------------------------------ #
    #  Public: Print a PNG on the label
    # ------------------------------------------------------------ #

    def build_png_image(
        self,
        png: _typing.StrOrBytesPath | IO[bytes],
        fit: str = "fit",
        width: int = None,
        height: int = None,
        x: int = 0,
        y: int = 0,
        margin_mm: float = 0.0,
        rotate: int = 0,
    ) -> Image.Image:
        """Load a PNG and scale it onto a full label canvas (no print).

        ``fit`` selects the scaling mode (see :meth:`_fit_image`). When an
        explicit ``width``/``height`` is given those take precedence (legacy
        exact sizing), composed at ``(x, y)``. ``margin_mm`` reserves a blank
        safety border (ignored under explicit ``width``/``height``). ``rotate``
        turns the content by 0/90/180/270° clockwise on the same label (see
        :meth:`_apply_rotation`).
        """
        if rotate % 360:
            return self._apply_rotation(
                lambda: self.build_png_image(
                    png, fit=fit, width=width, height=height, x=x, y=y,
                    margin_mm=margin_mm,
                ),
                rotate,
            )
        img = Image.open(png)

        if width is not None or height is not None:
            # Explicit sizing (legacy) — preserve aspect when only one is given.
            if width is not None and height is not None:
                img = img.resize((width, height), Image.Resampling.LANCZOS)
            elif width is not None:
                h = int(width * img.height / img.width)
                img = img.resize((width, h), Image.Resampling.LANCZOS)
            else:
                w = int(height * img.width / img.height)
                img = img.resize((w, height), Image.Resampling.LANCZOS)
            return self._compose_on_canvas(img, x, y)

        return self._fit_image(img, fit, margin_mm=margin_mm)

    def print_png(
        self,
        png: _typing.StrOrBytesPath | IO[bytes],
        fit: str = "fit",
        width: int = None,
        height: int = None,
        x: int = 0,
        y: int = 0,
        copies: int = 1,
        margin_mm: float = 0.0,
        rotate: int = 0,
    ):
        """
        Print a PNG image on the label.

        Args:
            png: Path to PNG file or file-like object.
            fit: Scaling mode — ``fit`` (contain), ``fill`` (cover/crop),
                ``stretch`` or ``original`` (see :meth:`_fit_image`). Ignored when
                an explicit ``width``/``height`` is given.
            width, height: Optional explicit target size in pixels (legacy).
            x, y: Position in pixels when explicit sizing is used.
            copies: Number of labels to print.
            margin_mm: Blank safety border to reserve on all sides (see
                :meth:`_fit_image`).
            rotate: Rotate the content by 0/90/180/270° clockwise on the same
                label (see :meth:`_apply_rotation`).
        """
        img = self.build_png_image(
            png, fit=fit, width=width, height=height, x=x, y=y,
            margin_mm=margin_mm, rotate=rotate,
        )
        self._render_and_print_image(img, 0, 0, copies=copies)

    # ------------------------------------------------------------ #
    #  Public: Print a PDF on the label
    # ------------------------------------------------------------ #

    def print_pdf(
        self,
        pdf: _typing.StrOrBytesPath | IO[bytes],
        page: Union[int, Literal["all"]] = 0,
        fit: str = "fit",
        copies: int = 1,
        margin_mm: float = 0.0,
        rotate: int = 0,
    ):
        """
        Render PDF page(s) to a label-sized bitmap and print.

        Uses pypdfium2 (a self-contained wheel, no system dependency). Each page
        is scaled onto the label per ``fit`` (``fit``/``fill``/``stretch``/
        ``original`` — see :meth:`_fit_image`) and printed as a separate label.

        Args:
            pdf: Path to a PDF file or a file-like object / bytes.
            page: Zero-based page index, or "all" to print every page.
            fit: Scaling mode for each page.
            copies: Copies per page.
            margin_mm: Blank safety border to reserve on all sides.
            rotate: Rotate each page by 0/90/180/270° clockwise on the same
                label (see :meth:`_apply_rotation`).
        """
        for img in self._render_pdf_pages(pdf, page):
            page_img = self._apply_rotation(
                lambda img=img: self._fit_image(img, fit, margin_mm=margin_mm), rotate
            )
            self._render_and_print_image(page_img, 0, 0, copies=copies)

    def _render_pdf_pages(
        self,
        pdf: _typing.StrOrBytesPath | IO[bytes],
        page: Union[int, Literal["all"]] = 0,
    ):
        """Yield PIL images for the requested PDF page(s), at a bounded resolution.

        Each page is rendered at its natural aspect ratio with the longer side at
        ~1.5× the longer label side — enough detail for any fit mode (incl. crop)
        without rendering huge bitmaps. Scaling to the label happens later via
        :meth:`_fit_image`.
        """
        import pypdfium2 as pdfium

        # pypdfium2 accepts a path or bytes; normalize file-like objects to bytes.
        if hasattr(pdf, "read"):
            pdf_input = pdf.read()
        else:
            pdf_input = pdf

        target_long = max(1, round(1.5 * max(self.width_px, self.height_px)))
        doc = pdfium.PdfDocument(pdf_input)
        try:
            if page == "all":
                page_indices = range(len(doc))
            else:
                if page < 0 or page >= len(doc):
                    raise ValueError(
                        f"PDF page {page} out of range (document has {len(doc)} pages)"
                    )
                page_indices = [page]

            for index in page_indices:
                pdf_page = doc[index]
                point_w, point_h = pdf_page.get_size()  # points (1/72 inch)
                point_long = max(point_w, point_h) or 1
                # pypdfium render scale is relative to 72 dpi: px = points * scale.
                scale = target_long / point_long
                bitmap = pdf_page.render(scale=scale, draw_annots=True)
                yield bitmap.to_pil()
        finally:
            doc.close()

    def build_pdf_image(
        self,
        pdf: _typing.StrOrBytesPath | IO[bytes],
        page: Union[int, Literal["all"]] = 0,
        fit: str = "fit",
        margin_mm: float = 0.0,
        rotate: int = 0,
    ) -> Image.Image:
        """Render a single PDF page to a label image (no print).

        For a preview, ``"all"`` falls back to the first page. ``rotate`` turns
        the page by 0/90/180/270° clockwise on the same label (see
        :meth:`_apply_rotation`).
        """
        index = 0 if page == "all" else page
        for img in self._render_pdf_pages(pdf, index):
            return self._apply_rotation(
                lambda: self._fit_image(img, fit, margin_mm=margin_mm), rotate
            )
        raise ValueError("PDF has no pages to render")

    # ------------------------------------------------------------ #
    #  Public: Print plain text
    # ------------------------------------------------------------ #

    @staticmethod
    def _wrap_to_width(draw, text: str, font, max_w: int) -> List[str]:
        """Word-wrap ``text`` so each line's rendered width fits ``max_w`` pixels.

        A single word wider than ``max_w`` is kept on its own line (it overflows
        rather than being split).
        """
        lines: List[str] = []
        current = ""
        for word in text.split(" "):
            trial = f"{current} {word}".strip()
            if not current or draw.textlength(trial, font=font) <= max_w:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    def _render_text_block(
        self,
        items: List[tuple[str, float]],
        x: int,
        y: int,
        base_size: Optional[int] = None,
        fit: str = "fill",
        line_spacing: int = 4,
        font_path: str = DEFAULT_FONT_PATH,
        min_size: int = 8,
    ) -> Image.Image:
        """Render text lines onto a label canvas, optionally auto-fitting size.

        ``items`` is a list of ``(text, weight)`` pairs; each line's font size is
        ``base_size * weight`` (so e.g. a markdown ``#`` heading with weight 2.0
        is twice the body size).

        When ``base_size`` is ``None`` the size is chosen automatically per
        ``fit``:
          - ``"fill"`` (default): the largest size whose *word-wrapped* block fits
            the label's printable area (width and height) — text grows to fill the
            label, wrapping as needed.
          - ``"width"``: the largest size at which every line fits the label
            *width without wrapping* (preserving your line breaks); height may be
            left partly blank. Falls back to ``"fill"`` if a line is too long to
            fit unwrapped at the minimum size.
        When ``base_size`` is given it is used as-is (``fit`` still controls
        whether long lines are wrapped).
        """
        scratch = ImageDraw.Draw(Image.new("1", (1, 1), 1))
        avail_w = max(1, self.width_px - 2 * x)
        avail_h = max(1, self.height_px - 2 * y)

        def layout(base: int, wrap: bool):
            """Return (total_height, max_width, [(chunk, font), ...])."""
            rendered: List[tuple[str, ImageFont.FreeTypeFont]] = []
            total_h = 0
            max_w = 0
            for text, weight in items:
                font = ImageFont.truetype(font_path, max(1, int(round(base * weight))))
                ascent, descent = font.getmetrics()
                line_height = ascent + descent + line_spacing
                if not text:
                    total_h += line_height
                    continue
                chunks = (
                    self._wrap_to_width(scratch, text, font, avail_w)
                    if wrap
                    else [text]
                )
                for chunk in chunks:
                    rendered.append((chunk, font))
                    max_w = max(max_w, int(scratch.textlength(chunk, font=font)))
                    total_h += line_height
            return total_h, max_w, rendered

        def largest_fitting(wrap: bool, hi: int) -> int:
            lo, best = min_size, min_size
            while lo <= hi:
                mid = (lo + hi) // 2
                total_h, max_w, _ = layout(mid, wrap)
                if total_h <= avail_h and max_w <= avail_w:
                    best = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            return best

        wrap = True
        if base_size is None:
            if fit == "width" and layout(min_size, wrap=False)[1] <= avail_w:
                # Every line fits unwrapped at the floor: size to width, no wrapping.
                base_size = largest_fitting(wrap=False, hi=max(avail_w, avail_h))
                wrap = False
            else:
                # "fill" (or a line too long for "width" → fall back to fill).
                base_size = largest_fitting(wrap=True, hi=avail_h)
        else:
            wrap = fit != "width"

        rendered = layout(base_size, wrap)[2]

        img = Image.new("1", (self.width_px, self.height_px), 1)
        draw = ImageDraw.Draw(img)
        offset = y
        for chunk, font in rendered:
            ascent, descent = font.getmetrics()
            draw.text((x, offset), chunk, font=font, fill=0)
            offset += ascent + descent + line_spacing
        return img

    def print_text(
        self,
        text: str,
        x: int = 10,
        y: int = 10,
        font_size: Optional[int] = None,
        fit: str = "fill",
        font_path: str = DEFAULT_FONT_PATH,
        copies: int = 1,
        rotate: int = 0,
    ):
        """
        Render plain text to the label with word wrapping.

        Args:
            text: The text to print (newlines preserved, long lines wrapped).
            x, y: Top-left origin / margin in pixels.
            font_size: Font size in pixels. If ``None`` (default), the text is
                auto-scaled; pass a value to fix the size.
            fit: Auto-scale mode when ``font_size`` is None — ``"fill"`` (grow to
                fill width and height, wrapping as needed) or ``"width"`` (size to
                the label width, keeping your line breaks).
            font_path: TrueType font to use.
            copies: Number of labels to print.
            rotate: Rotate the text by 0/90/180/270° clockwise on the same label;
                auto-fit adapts to the rotated shape (see :meth:`_apply_rotation`).
        """
        img = self.build_text_image(
            text, x=x, y=y, font_size=font_size, fit=fit, font_path=font_path,
            rotate=rotate,
        )
        self._render_and_print_image(img, 0, 0, copies=copies)

    def build_text_image(
        self,
        text: str,
        x: int = 10,
        y: int = 10,
        font_size: Optional[int] = None,
        fit: str = "fill",
        font_path: str = DEFAULT_FONT_PATH,
        rotate: int = 0,
    ) -> Image.Image:
        """Render plain text to a full label image (no print). See ``print_text``."""
        if rotate % 360:
            return self._apply_rotation(
                lambda: self.build_text_image(
                    text, x=x, y=y, font_size=font_size, fit=fit, font_path=font_path
                ),
                rotate,
            )
        items = [(line.rstrip(), 1.0) for line in (text.splitlines() or [""])]
        return self._render_text_block(
            items, x, y, base_size=font_size, fit=fit, font_path=font_path
        )

    # ------------------------------------------------------------ #
    #  Public: Print an alignment / sizing test pattern (#1B)
    # ------------------------------------------------------------ #

    def print_test_pattern(self, copies: int = 1):
        """
        Print a diagnostic pattern to verify positioning and sizing on hardware:
        a full border, corner ticks, mm ruler ticks along the top/left edges, a
        centered crosshair, and the label's mm/px dimensions as text. A correctly
        configured label shows the border flush to all four edges with the ruler
        ticks landing on whole millimetres.
        """
        img = Image.new("1", (self.width_px, self.height_px), 1)
        draw = ImageDraw.Draw(img)
        w, h = self.width_px - 1, self.height_px - 1
        dots_per_mm = self.dpi / 25.4

        # Full border
        draw.rectangle([0, 0, w, h], outline=0, width=1)

        # mm ruler ticks: long every 5mm, short otherwise
        mm = 0
        while mm * dots_per_mm <= w:
            px = int(mm * dots_per_mm)
            length = 12 if mm % 5 == 0 else 6
            draw.line([(px, 0), (px, length)], fill=0, width=1)
            mm += 1
        mm = 0
        while mm * dots_per_mm <= h:
            py = int(mm * dots_per_mm)
            length = 12 if mm % 5 == 0 else 6
            draw.line([(0, py), (length, py)], fill=0, width=1)
            mm += 1

        # Centered crosshair
        cx, cy = self.width_px // 2, self.height_px // 2
        draw.line([(cx, cy - 15), (cx, cy + 15)], fill=0, width=1)
        draw.line([(cx - 15, cy), (cx + 15, cy)], fill=0, width=1)

        # Dimension label
        try:
            font = ImageFont.truetype(DEFAULT_FONT_PATH, 20)
        except Exception:
            font = ImageFont.load_default()
        draw.text(
            (16, 16),
            f"{self.width_mm}x{self.height_mm}mm @ {self.dpi}dpi "
            f"= {self.width_px}x{self.height_px}px",
            font=font,
            fill=0,
        )

        self._render_and_print_image(img, 0, 0, copies=copies)

    # ------------------------------------------------------------ #
    #  Public: Print basic markdown
    # ------------------------------------------------------------ #

    # Relative font-size weights for markdown line types (× base body size).
    _MD_H1_WEIGHT = 2.0
    _MD_H2_WEIGHT = 1.5
    _MD_BODY_WEIGHT = 1.0

    def print_markdown(
        self,
        md_text,
        x=10,
        y=10,
        font_path=DEFAULT_FONT_PATH,
        base_font_size: Optional[int] = None,
        fit: str = "fill",
        copies: int = 1,
        rotate: int = 0,
    ):
        """
        Very basic markdown → text rendering:
          # Heading        -> large, uppercase
          ## Subheading    -> medium, uppercase
          * bullet lists   -> body
          **bold**         -> uppercase
          normal paragraphs-> body

        Headings keep their relative size (# = 2× body, ## = 1.5×). If
        ``base_font_size`` is ``None`` (default) the body size is auto-scaled
        per ``fit`` (``"fill"`` = grow to fill the label, ``"width"`` = size to
        the label width keeping line breaks); pass a value to fix the body size.
        """
        img = self.build_markdown_image(
            md_text, x=x, y=y, font_path=font_path, base_font_size=base_font_size,
            fit=fit, rotate=rotate,
        )
        self._render_and_print_image(img, 0, 0, copies=copies)

    def build_markdown_image(
        self,
        md_text,
        x=10,
        y=10,
        font_path=DEFAULT_FONT_PATH,
        base_font_size: Optional[int] = None,
        fit: str = "fill",
        rotate: int = 0,
    ) -> Image.Image:
        """Render basic markdown to a full label image (no print). See ``print_markdown``."""
        if rotate % 360:
            return self._apply_rotation(
                lambda: self.build_markdown_image(
                    md_text, x=x, y=y, font_path=font_path,
                    base_font_size=base_font_size, fit=fit,
                ),
                rotate,
            )
        items: List[tuple[str, float]] = []
        for line in md_text.splitlines():
            line = line.strip()

            if not line:
                items.append(("", self._MD_BODY_WEIGHT))
            elif line.startswith("## "):
                items.append((line[3:].upper(), self._MD_H2_WEIGHT))
            elif line.startswith("# "):
                items.append((line[2:].upper(), self._MD_H1_WEIGHT))
            else:
                if line.startswith("* "):
                    txt = "• " + line[2:]
                else:
                    txt = line
                if "**" in txt:
                    txt = txt.replace("**", "").upper()
                items.append((txt, self._MD_BODY_WEIGHT))

        return self._render_text_block(
            items, x, y, base_size=base_font_size, fit=fit, font_path=font_path
        )

    def print_barcode(
        self,
        data: str,
        x: int = None,
        y: int = None,
        barcode_type: str = "128",
        height: int = None,
        readable: bool = True,
        rotation: int = 0,
        narrow_bar: int = 2,
        wide_bar: int = 6,
        copies: int = 1,
    ):
        """
        Print a barcode on the label.

        Args:
            data: Barcode data to encode
            x: X position in pixels (default: centered horizontally)
            y: Y position in pixels (default: 10% from top)
            barcode_type: Barcode type. Options:
                - "128" (Code 128, default - good for alphanumeric)
                - "128M" (Code 128 Manual)
                - "EAN13" (EAN-13, requires 12-13 digits)
                - "EAN8" (EAN-8, requires 7-8 digits)
                - "39" (Code 39)
                - "93" (Code 93)
                - "UPCA" (UPC-A, requires 11-12 digits)
                - "UPCE" (UPC-E, requires 6-8 digits)
                - "I25" (Interleaved 2 of 5)
            height: Barcode height in pixels (default: 40% of label height)
            readable: Show human-readable text below barcode
            rotation: Rotation angle (0, 90, 180, 270)
            narrow_bar: Width of narrow bar in dots (1-10, default: 2)
            wide_bar: Width of wide bar in dots (2-30, default: 6)
        """
        # Set defaults based on label size
        if height is None:
            height = int(self.height_px * 0.4)  # 40% of label height

        if x is None:
            # Center horizontally (approximate, depends on barcode width)
            x = int(self.width_px * 0.1)  # Start at 10% from left

        if y is None:
            y = int(self.height_px * 0.1)  # 10% from top

        # Ensure height is reasonable
        height = min(height, int(self.height_px * 0.8))

        human_readable = 1 if readable else 0

        self._set_size()
        self.cls()
        self._send(
            f'BARCODE {x},{y},"{barcode_type}",{height},{human_readable},'
            f'{rotation},{narrow_bar},{wide_bar},"{data}"\n'
        )
        self.print_label(copies=copies)

    # TSPL barcode-type code → python-barcode class name (preview rendering only).
    _BARCODE_TYPE_MAP = {
        "128": "code128",
        "128M": "code128",
        "EAN13": "ean13",
        "EAN8": "ean8",
        "39": "code39",
        "UPCA": "upca",
        "I25": "itf",
    }

    def build_barcode_image(
        self,
        data: str,
        barcode_type: str = "128",
        text: Optional[str] = None,
        readable: bool = True,
        font_path: str = DEFAULT_FONT_PATH,
    ) -> Image.Image:
        """Render a barcode to a full label image for **preview** (no print).

        On hardware, barcodes are emitted as native TSPL ``BARCODE`` commands
        (crisp, printer-rendered); this Python rendering (via ``python-barcode``)
        is a faithful-enough stand-in so the web UI can preview them. An optional
        ``text`` caption is drawn above the barcode (matching
        ``print_barcode_with_text``). Unsupported TSPL types fall back to Code 128.
        """
        import barcode as _barcode
        from barcode.writer import ImageWriter

        name = self._BARCODE_TYPE_MAP.get(barcode_type.upper(), "code128")
        try:
            cls = _barcode.get_barcode_class(name)
            obj = cls(str(data), writer=ImageWriter())
        except Exception:
            cls = _barcode.get_barcode_class("code128")
            obj = cls(str(data), writer=ImageWriter())

        bc_img = obj.render(
            {
                "module_height": 8.0,
                "font_size": 8,
                "text_distance": 2.0,
                "quiet_zone": 2.0,
                "write_text": readable,
            }
        )

        canvas = Image.new("L", (self.width_px, self.height_px), 255)
        draw = ImageDraw.Draw(canvas)
        margin = 8
        avail_w = max(1, self.width_px - 2 * margin)

        # Optional caption above the barcode.
        cap_h = 0
        if text:
            band = min(self.height_px // 3, max(16, int(self.height_px * 0.25)))
            font = self._fit_single_line_font(draw, text, avail_w, band, font_path)
            ascent, descent = font.getmetrics()
            cap_h = ascent + descent + margin
            tw = int(draw.textlength(text, font=font))
            draw.text((max(0, (self.width_px - tw) // 2), margin), text, font=font, fill=0)

        # Fit the barcode into the remaining area, preserving aspect ratio.
        area_w = avail_w
        area_h = max(1, self.height_px - cap_h - 2 * margin)
        ratio = min(area_w / bc_img.width, area_h / bc_img.height)
        new_size = (max(1, int(bc_img.width * ratio)), max(1, int(bc_img.height * ratio)))
        bc_img = bc_img.convert("L").resize(new_size, Image.NEAREST)

        bx = (self.width_px - bc_img.width) // 2
        by = cap_h + margin + (area_h - bc_img.height) // 2
        canvas.paste(bc_img, (max(0, bx), max(0, by)))
        return canvas

    def _qr_image(self, data: str, ecc_level: str = "M", border: int = 4) -> Image.Image:
        """Build a 1-bit QR image at 1 pixel per module (incl. quiet zone).

        Rendered with segno and scaled later with nearest-neighbour so modules
        stay crisp. ``border`` is the quiet-zone width in modules (4 = the QR
        spec minimum for reliable scanning).
        """
        import segno

        qr = segno.make(str(data), error=ecc_level.lower())
        matrix = list(qr.matrix)
        n = len(matrix)

        framed = Image.new("1", (n + 2 * border, n + 2 * border), 1)  # white
        px = framed.load()
        for r, row in enumerate(matrix):
            for c, bit in enumerate(row):
                if bit:
                    px[c + border, r + border] = 0  # black module
        return framed

    def _scaled_qr(self, data: str, ecc_level: str, target_px: int, border: int) -> Image.Image:
        """Return a QR image scaled (nearest-neighbour) to ~``target_px`` square."""
        qr = self._qr_image(data, ecc_level, border)
        module_px = max(1, target_px // qr.width)
        size = module_px * qr.width
        return qr.resize((size, size), Image.NEAREST)

    def print_qrcode(
        self,
        data: str,
        x: int = None,
        y: int = None,
        ecc_level: str = "M",
        scale: float = 0.9,
        border: int = 4,
        rotation: int = 0,
        copies: int = 1,
    ):
        """
        Print a QR code, scaled to fill the label and centered.

        The QR is rendered to a bitmap (via segno) sized to ``scale`` × the
        smaller label dimension, then printed through the shared image pipeline —
        so it is as large as fits and properly centered, regardless of how many
        modules the data needs.

        Args:
            data: Data to encode (text / URL / asset id).
            x, y: Top-left position in pixels (default: centered).
            ecc_level: Error correction level "L" / "M" / "Q" / "H".
            scale: Fraction of the smaller label dimension to fill (0–1, default 0.9).
            border: Quiet-zone width in modules (default 4, the spec minimum).
            rotation: 0/90/180/270 degrees.
            copies: Number of labels to print.
        """
        canvas = self.build_qrcode_image(
            data, x=x, y=y, ecc_level=ecc_level, scale=scale, border=border,
            rotation=rotation,
        )
        self._render_and_print_image(canvas, 0, 0, copies=copies)

    def build_qrcode_image(
        self,
        data: str,
        x: int = None,
        y: int = None,
        ecc_level: str = "M",
        scale: float = 0.9,
        border: int = 4,
        rotation: int = 0,
    ) -> Image.Image:
        """Render a centered QR to a full label image (no print). See ``print_qrcode``."""
        target = max(1, int(min(self.width_px, self.height_px) * scale))
        qr_img = self._scaled_qr(data, ecc_level, target, border)
        if rotation in (90, 180, 270):
            qr_img = qr_img.rotate(-rotation, expand=True)

        canvas = Image.new("1", (self.width_px, self.height_px), 1)
        qx = x if x is not None else (self.width_px - qr_img.width) // 2
        qy = y if y is not None else (self.height_px - qr_img.height) // 2
        canvas.paste(qr_img, (max(0, qx), max(0, qy)))
        return canvas

    def print_barcode_with_text(
        self,
        barcode_data: str,
        text: str = None,
        barcode_type: str = "128",
        font_size: int = 3,
        copies: int = 1,
    ):
        """
        Print a barcode with custom text above or below it.
        Automatically layouts barcode and text on the label.

        Args:
            barcode_data: Data to encode in barcode
            text: Additional text to print (default: None, only barcode printed)
            barcode_type: Barcode type (see print_barcode for options)
            font_size: Font size for text (1-8)
        """
        self._set_size()
        self.cls()

        # Calculate layout
        text_height = 20 * font_size if text else 0
        barcode_height = int((self.height_px - text_height - 20) * 0.8)

        # Print text at top if provided
        if text:
            text_y = 10
            self._send(f'TEXT 10,{text_y},"3",0,1,1,"{text}"\n')

        # Print barcode below text
        barcode_y = text_height + 10 if text else int(self.height_px * 0.1)
        barcode_x = int(self.width_px * 0.1)

        self._send(
            f'BARCODE {barcode_x},{barcode_y},"{barcode_type}",{barcode_height},1,'
            f'0,2,6,"{barcode_data}"\n'
        )

        self.print_label(copies=copies)

    def _fit_single_line_font(
        self, draw, text: str, max_w: int, max_h: int, font_path: str, min_size: int = 8
    ) -> ImageFont.FreeTypeFont:
        """Largest font at which ``text`` fits on one line within max_w × max_h."""
        # PIL's textlength() raises on embedded newlines; this fitter is single
        # line by contract, so flatten defensively regardless of caller (#5).
        text = " ".join(text.split())
        lo, hi, best = min_size, max(min_size, max_h), min_size
        while lo <= hi:
            mid = (lo + hi) // 2
            font = ImageFont.truetype(font_path, mid)
            ascent, descent = font.getmetrics()
            if draw.textlength(text, font=font) <= max_w and ascent + descent <= max_h:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return ImageFont.truetype(font_path, best)

    def print_qrcode_with_text(
        self,
        qr_data: str,
        text: str = None,
        text_position: str = "bottom",
        ecc_level: str = "M",
        font_size: int = None,
        font_path: str = DEFAULT_FONT_PATH,
        border: int = 4,
        copies: int = 1,
    ):
        """
        Print a QR code with a text caption, both scaled to the label.

        The QR fills the area not used by the text; the caption is sized to fit
        the label width (or fixed via ``font_size``). Everything is rendered to a
        bitmap and printed through the shared image pipeline. With no ``text``
        this behaves like :meth:`print_qrcode`.

        Args:
            qr_data: Data to encode (text / URL / asset id).
            text: Caption to display (default: None).
            text_position: "top" or "bottom" (default: "bottom").
            ecc_level: Error correction level "L" / "M" / "Q" / "H".
            font_size: Fixed caption font size in px (default: auto-fit to width).
            border: QR quiet-zone width in modules.
            copies: Number of labels to print.
        """
        if not text:
            return self.print_qrcode(
                qr_data, ecc_level=ecc_level, border=border, copies=copies
            )
        canvas = self.build_qrcode_with_text_image(
            qr_data, text=text, text_position=text_position, ecc_level=ecc_level,
            font_size=font_size, font_path=font_path, border=border,
        )
        self._render_and_print_image(canvas, 0, 0, copies=copies)

    def print_raw_tspl(self, tspl: str, copies: int = 1) -> None:
        """Отправить готовую TSPL-программу в принтер как есть.

        Строка ``tspl`` должна содержать полный набор команд, включая
        финальный ``PRINT n``. Кодируется в cp1251, чтобы соответствовать
        ``CODEPAGE \"1251\"`` в шаблоне. Параметр ``copies`` не используется —
        количество копий контролируется самой TSPL-программой.
        """
        payload = tspl.encode("cp1251", errors="replace")
        if not payload.endswith(b"\n"):
            payload += b"\n"
        if self.dry_run_mode:
            print(payload)
            return
        # raw=True + bytes → _to_wire вернёт байты как есть, без ASCII-перекодировки
        # и без добавления \n. Это критично для кириллицы в cp1251.
        self.connection.send(payload, raw=True)

    def build_qrcode_with_text_image(
        self,
        qr_data: str,
        text: str = None,
        text_position: str = "bottom",
        ecc_level: str = "M",
        font_size: int = None,
        font_path: str = DEFAULT_FONT_PATH,
        border: int = 4,
    ) -> Image.Image:
        """Render a QR + caption to a full label image (no print). See ``print_qrcode_with_text``."""
        if not text:
            return self.build_qrcode_image(qr_data, ecc_level=ecc_level, border=border)

        # Caption is a single line; flatten any newlines so PIL's textlength()
        # (used to fit and to place the caption) never sees multiline text (#5).
        text = " ".join(text.split())

        margin = 8
        canvas = Image.new("1", (self.width_px, self.height_px), 1)
        draw = ImageDraw.Draw(canvas)
        avail_w = max(1, self.width_px - 2 * margin)

        # Reserve a band for the caption (~18% of height), then size its font.
        text_band = min(self.height_px - 2 * margin, max(24, int(self.height_px * 0.18)))
        if font_size is not None:
            font = ImageFont.truetype(font_path, font_size)
        else:
            font = self._fit_single_line_font(draw, text, avail_w, text_band, font_path)
        ascent, descent = font.getmetrics()
        text_h = ascent + descent

        # QR fills the remaining square area.
        qr_area_h = self.height_px - 2 * margin - text_h
        qr_target = max(1, min(avail_w, qr_area_h))
        qr_img = self._scaled_qr(qr_data, ecc_level, qr_target, border)

        if text_position == "top":
            text_y = margin
            qr_top = margin + text_h
        else:
            qr_top = margin
            text_y = self.height_px - margin - text_h

        qr_x = (self.width_px - qr_img.width) // 2
        qr_y = qr_top + (qr_area_h - qr_img.height) // 2
        canvas.paste(qr_img, (max(0, qr_x), max(0, qr_y)))

        text_w = int(draw.textlength(text, font=font))
        draw.text(
            (max(0, (self.width_px - text_w) // 2), text_y), text, font=font, fill=0
        )

        return canvas
