#!/usr/bin/env python3
"""
LabelJetty test bench.

A small CLI to drive the TSPLPrinter library directly — against the real USB
printer, or in --dry-run mode where the generated TSPL is printed to stdout
instead of the device. Handy for verifying positioning/sizing on the Vretti.

Label geometry defaults come from the config/env vars (DEFAULT_LABEL_WIDTH_MM,
DEFAULT_LABEL_HEIGHT_MM, DEFAULT_DPI in the repo-root .env); pass
--width-mm / --height-mm / --dpi to override per run.

Examples (run from the repository root):

    uv run labeljetty-testbench --dry-run pattern
    uv run labeljetty-testbench --width-mm 50 --height-mm 30 pattern
    uv run labeljetty-testbench text "Hello world"
    uv run labeljetty-testbench status
"""
import argparse
import sys

from labeljetty.printer import TSPLPrinter


def _label_defaults() -> tuple[int, int, int]:
    """Default label geometry, sourced from the config/env vars
    (DEFAULT_LABEL_WIDTH_MM / DEFAULT_LABEL_HEIGHT_MM / DEFAULT_DPI, read from
    the repo-root .env). Falls back to 100x30mm @ 203dpi only if the
    config can't be loaded (e.g. dry-run with no .env present).
    """
    try:
        from labeljetty.config import Config

        c = Config()
        return c.DEFAULT_LABEL_WIDTH_MM, c.DEFAULT_LABEL_HEIGHT_MM, c.DEFAULT_DPI
    except Exception:
        return 100, 30, 203


def build_printer(args) -> TSPLPrinter:
    """Build a TSPLPrinter, honoring --dry-run / --usb / label geometry."""
    if args.dry_run:
        connection = None
    else:
        from labeljetty.config import Config

        config = Config()
        if args.usb:
            config.PRINTER_USB = args.usb
        connection = config.get_printer_connection()
        connection.connect()

    return TSPLPrinter(
        connection=connection,
        label_width_mm=args.width_mm,
        label_height_mm=args.height_mm,
        dpi=args.dpi,
        dry_run_mode=args.dry_run,
    )


def _read_loop(connection, attempts: int, timeout: int, read_len: int):
    """Read up to ``attempts`` times, returning the first non-empty reply (bytes)."""
    collected = b""
    for _ in range(attempts):
        data = connection.receive(timeout=timeout, max_length=read_len)
        if data:
            collected += data
    return collected


def probe_status(printer) -> int:
    """Send the TSPL real-time status query and report whether the printer answers.

    Only the documented, side-effect-free status command <ESC>!? (0x1B 0x21 0x3F)
    is sent. Useful to tell whether this printer implements USB status-read at all.
    """
    if printer.dry_run_mode:
        print("probe needs the real printer (do not pass --dry-run).", file=sys.stderr)
        return 2

    connection = printer.connection
    cmd = b"\x1b!?"
    print(f"Sending status query {cmd!r} ({cmd.hex(' ')}) and reading replies...\n")

    got_any = False
    for timeout in (300, 1000, 3000):
        # Drain any stale bytes first, then send and read.
        connection.receive(timeout=50, max_length=64)
        connection.send(cmd, raw=True)
        data = _read_loop(connection, attempts=3, timeout=timeout, read_len=64)
        if data:
            got_any = True
            print(f"timeout={timeout:>4}ms -> {len(data)} byte(s): "
                  f"hex={data.hex(' ')}  first=0x{data[0]:02x}")
        else:
            print(f"timeout={timeout:>4}ms -> (no reply)")

    print()
    if got_any:
        print("Printer answers the status query. If get_status() still fails, the "
              "timing/length in TSPLPrinter.get_status may need tuning.")
        return 0
    print("No reply to <ESC>!? — this printer likely does not support USB "
          "status-read, or uses a different command. Try the 'raw' subcommand with "
          "candidate queries, e.g.:  testbench.py raw '~!T' --text")
    return 1


def send_raw(printer, args) -> int:
    """Send arbitrary bytes and print whatever the printer replies (debug tool)."""
    if printer.dry_run_mode:
        print("raw needs the real printer (do not pass --dry-run).", file=sys.stderr)
        return 2

    if args.text:
        payload = args.data.encode("ascii")
    else:
        try:
            payload = bytes.fromhex(args.data.replace(" ", ""))
        except ValueError:
            print(f"error: '{args.data}' is not valid hex (use --text for literal text).",
                  file=sys.stderr)
            return 2

    connection = printer.connection
    print(f"Sending {payload!r} ({payload.hex(' ')})...")
    connection.send(payload, raw=True)
    data = connection.receive(timeout=args.timeout, max_length=args.read_len)
    if data:
        print(f"reply: {len(data)} byte(s)  hex={data.hex(' ')}  repr={data!r}")
        return 0
    print("reply: (no data / timeout)")
    return 1


def list_printers() -> int:
    """Print every auto-discovered TSPL printer as a copy-paste PRINTER_USB
    selector. The diagnostic for the multi-printer case: pick one line and put
    it in your .env."""
    from labeljetty.printer.connection import TSPLPrinterConnectionUSB as Conn

    devices = Conn.discover()
    if not devices:
        print("No TSPL printers detected. Connect the printer and power it on, "
              "then re-run. (`lsusb` lists all USB devices.)")
        return 1

    print(f"Detected {len(devices)} candidate TSPL printer(s):\n")
    for dev in devices:
        print(f"  PRINTER_USB={Conn.selector_for(dev)}   ({Conn.describe(dev)})")
    if len(devices) > 1:
        print("\nMore than one candidate — set PRINTER_USB to one of the above "
              "to pin it (auto-detect refuses to guess between several).")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="TSPL library test bench")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated TSPL to stdout instead of sending to the device.",
    )
    def_w, def_h, def_dpi = _label_defaults()
    parser.add_argument(
        "--width-mm", type=int, default=def_w,
        help=f"Label width in mm (default {def_w}, from DEFAULT_LABEL_WIDTH_MM).",
    )
    parser.add_argument(
        "--height-mm", type=int, default=def_h,
        help=f"Label height in mm (default {def_h}, from DEFAULT_LABEL_HEIGHT_MM).",
    )
    parser.add_argument(
        "--dpi", type=int, default=def_dpi,
        help=f"Printer DPI (default {def_dpi}, from DEFAULT_DPI).",
    )
    parser.add_argument(
        "--usb",
        default=None,
        help="Override PRINTER_USB selector (ignored in --dry-run).",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "list-printers",
        help="Auto-discover connected TSPL printers and print PRINTER_USB selectors.",
    )
    sub.add_parser("pattern", help="Print the alignment/ruler test pattern.")
    sub.add_parser("status", help="Query and print the live printer status.")
    sub.add_parser(
        "probe",
        help="Diagnose status-read: send <ESC>!? with varied timeouts and show raw bytes.",
    )

    p_raw = sub.add_parser(
        "raw",
        help="Send raw bytes to the printer and read the reply (debugging).",
    )
    p_raw.add_argument(
        "data",
        help="Bytes to send: hex like '1b213f', or text (use --text) like '~!T'.",
    )
    p_raw.add_argument(
        "--text",
        action="store_true",
        help="Treat DATA as literal text instead of a hex string.",
    )
    p_raw.add_argument("--timeout", type=int, default=2000, help="Read timeout (ms).")
    p_raw.add_argument("--read-len", type=int, default=64, help="Max bytes to read.")

    p_png = sub.add_parser("png", help="Print a PNG file.")
    p_png.add_argument("path")

    p_pdf = sub.add_parser("pdf", help="Print a PDF file.")
    p_pdf.add_argument("path")
    p_pdf.add_argument(
        "--page", default="0", help="Page index, or 'all' (default: 0)."
    )

    p_text = sub.add_parser("text", help="Print plain text.")
    p_text.add_argument("text")
    p_text.add_argument(
        "--font-size", type=int, default=None,
        help="Fixed font size in px. Omit to auto-scale the text.",
    )
    p_text.add_argument(
        "--fit", choices=["fill", "width"], default="fill",
        help="Auto-scale mode (default fill): 'fill' grows to fill the label; "
             "'width' sizes to the label width and keeps your line breaks.",
    )

    p_md = sub.add_parser("markdown", help="Print basic markdown.")
    p_md.add_argument("text")
    p_md.add_argument(
        "--fit", choices=["fill", "width"], default="fill",
        help="Auto-scale mode (default fill). See `text --help`.",
    )

    p_bc = sub.add_parser("barcode", help="Print a barcode.")
    p_bc.add_argument("data")
    p_bc.add_argument("--type", default="128", dest="barcode_type")
    p_bc.add_argument("--text", default=None, help="Optional human-readable text.")

    p_qr = sub.add_parser("qrcode", help="Print a QR code.")
    p_qr.add_argument("data")
    p_qr.add_argument("--ecc", default="M", dest="ecc_level")
    p_qr.add_argument("--text", default=None, help="Optional human-readable text.")

    args = parser.parse_args(argv)

    # Discovery diagnostic — runs without opening a printer.
    if args.command == "list-printers":
        return list_printers()

    try:
        printer = build_printer(args)
    except PermissionError as e:
        print(f"error: {e}", file=sys.stderr)
        return 13
    cmd = args.command

    if cmd == "pattern":
        printer.print_test_pattern()
    elif cmd == "status":
        status = printer.get_status()
        if status is None:
            print("status: not available — this printer does not answer status "
                  "queries (printing is unaffected). See 'probe' for details.")
        else:
            print(status.model_dump())
            print("error:", status.error)
            print("message:", printer.get_error_message())
    elif cmd == "probe":
        return probe_status(printer)
    elif cmd == "raw":
        return send_raw(printer, args)
    elif cmd == "png":
        printer.print_png(args.path)
    elif cmd == "pdf":
        page = args.page if args.page == "all" else int(args.page)
        printer.print_pdf(args.path, page=page)
    elif cmd == "text":
        printer.print_text(args.text, font_size=args.font_size, fit=args.fit)
    elif cmd == "markdown":
        printer.print_markdown(args.text, fit=args.fit)
    elif cmd == "barcode":
        if args.text:
            printer.print_barcode_with_text(
                args.data, text=args.text, barcode_type=args.barcode_type
            )
        else:
            printer.print_barcode(args.data, barcode_type=args.barcode_type)
    elif cmd == "qrcode":
        if args.text:
            printer.print_qrcode_with_text(
                args.data, text=args.text, ecc_level=args.ecc_level
            )
        else:
            printer.print_qrcode(args.data, ecc_level=args.ecc_level)
    else:  # pragma: no cover - argparse enforces valid commands
        parser.error(f"Unknown command: {cmd}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
