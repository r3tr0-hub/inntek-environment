import traceback
import usb.core
import usb.util
import time
from typing import Optional, List, Union, cast, Self
from usb.core import Device, Endpoint, Configuration, Interface, USBError
import glob
import os


# Curated allowlist of USB vendor IDs known to speak TSPL, used by auto-discovery
# when PRINTER_USB is unset. The value is a human-readable label for log output.
# This list is meant to GROW from verified user reports — add an entry here when a
# new TSPL printer is confirmed (see docs/hardware.md). Unknown printers are still
# picked up by the USB printer-class heuristic (see ``discover``), so this list is
# a precision aid, not the only path to detection.
KNOWN_TSPL_VENDORS: dict[int, str] = {
    0x2D37: "Poskey / Vretti-class (e.g. 420B)",  # verified reference hardware
}

# USB interface class for printers (USB-IF base class 7). Devices advertising it
# are treated as discovery candidates even if their vendor id is not in the
# allowlist above.
_USB_CLASS_PRINTER = 7


def _fresh_backend():
    """A libusb backend backed by a brand-new context, falling back to pyusb's
    shared backend if the internals differ.

    Why not just use pyusb's default (cached) backend: libusb enumerates the
    USB bus once when its context is created and thereafter learns about
    plug/unplug only from udev/netlink ``uevents``. Inside a container those
    uevents typically never arrive, so the cached context goes stale — a
    printer replugged onto a new ``/dev/bus/usb`` node stays invisible (it
    keeps handing back the dead node), and a printer plugged in after startup
    is never seen at all. This is issue #4.

    A fresh ``libusb_init`` always re-reads sysfs, so it reflects the current
    device nodes even with no uevents. The bind-mounted ``/dev/bus/usb`` +
    ``device_cgroup_rules`` (see docker-compose.yml) make those nodes appear
    live in the container; enumerating through a new context here is what makes
    the app actually act on them. Detection already re-runs on every status
    poll and every job, so a per-scan context has no practical cost.

    Uses pyusb internals (``_LibUSB``) because pyusb exposes no public API for
    forcing a new context. ``get_backend()`` first loads the shared library and
    populates the module globals that enumeration relies on; we then wrap that
    same library in a new libusb context.
    """
    try:
        from usb.backend import libusb1

        shared = libusb1.get_backend()
        if shared is None or libusb1._lib is None:
            return shared  # libusb unavailable or unexpected state — use default
        return libusb1._LibUSB(libusb1._lib)  # new libusb_init => fresh sysfs scan
    except Exception:
        return None


def _find(**kwargs):
    """``usb.core.find`` wrapper that always enumerates through a fresh libusb
    context, so hotplugged printers are seen inside containers (issue #4)."""
    return usb.core.find(backend=_fresh_backend(), **kwargs)


class TSPLPrinterConnectionUSB:
    """
    Automatically detects a TSPL printer by probing USB devices and sending
    a harmless TSPL query command (~!T). Maintains connection and allows
    sending TSPL commands via .send().
    """

    # ----------------------------------
    # --- Lookup: Auto-discovery     ---
    # ----------------------------------
    @staticmethod
    def selector_for(dev: Device) -> str:
        """The ``PRINTER_USB=vid:..:pid:..`` selector that pins this exact device."""
        return f"vid:{dev.idVendor:04x}:pid:{dev.idProduct:04x}"

    @staticmethod
    def describe(dev: Device) -> str:
        """Best-effort human label for ``dev`` (manufacturer/product strings plus a
        known-vendor note). Never raises — string-descriptor reads can fail on
        permissions, so they are treated as optional."""
        parts: List[str] = []
        for attr in ("iManufacturer", "iProduct"):
            try:
                value = usb.util.get_string(dev, getattr(dev, attr))
            except Exception:
                value = None
            if value:
                parts.append(value)
        label = " ".join(parts).strip()
        known = KNOWN_TSPL_VENDORS.get(dev.idVendor)
        if label and known:
            return f"{label} — {known}"
        return label or known or "unknown device"

    @staticmethod
    def _is_printer_class(dev: Device) -> bool:
        """True if any interface advertises the USB printer class (7).

        Reads only the already-enumerated descriptors — no device is claimed.
        """
        try:
            for cfg in dev:
                for intf in cfg:
                    if intf.bInterfaceClass == _USB_CLASS_PRINTER:
                        return True
        except Exception:
            pass
        return False

    @classmethod
    def _matches(cls, dev: Device) -> bool:
        """Discovery predicate: known TSPL vendor OR generic USB printer class."""
        if dev.idVendor in KNOWN_TSPL_VENDORS:
            return True
        return cls._is_printer_class(dev)

    @classmethod
    def discover(cls) -> List[Device]:
        """Passively enumerate USB devices that look like TSPL printers.

        A device is a candidate when its vendor id is in ``KNOWN_TSPL_VENDORS`` or
        it exposes the USB printer interface class (7). This is pure descriptor
        enumeration — nothing is claimed, no kernel driver is detached, nothing is
        written to the device — so it is safe to run unattended (e.g. on every job
        when ``PRINTER_USB`` is unset).
        """
        found = _find(find_all=True)
        if found is None:
            return []
        return [dev for dev in found if cls._matches(dev)]

    @classmethod
    def autodetect(cls) -> Self:
        """Resolve the connection by auto-discovery, used when ``PRINTER_USB`` is
        unset. Decides among the discovered candidates:

        - 0 found  -> ``ValueError`` telling the user to plug in / set PRINTER_USB.
        - 1 found  -> use it (and report which one, so it can be pinned in .env).
        - 2+ found -> ``ValueError`` listing each as a copy-paste PRINTER_USB
          selector; auto-detect deliberately does not guess.
        """
        candidates = cls.discover()

        if not candidates:
            raise ValueError(
                "No TSPL printer auto-detected. Connect the printer and power it "
                "on, or set PRINTER_USB manually — run `lsusb` to find its "
                "vid:pid (see the Setup guide, 'Find your printer')."
            )

        if len(candidates) > 1:
            listing = "\n".join(
                f"    PRINTER_USB={cls.selector_for(d)}   ({cls.describe(d)})"
                for d in candidates
            )
            raise ValueError(
                "Multiple TSPL printers detected — auto-detect will not guess. "
                "Set PRINTER_USB to one of:\n" + listing
            )

        dev = candidates[0]
        print(
            f"Auto-detected TSPL printer: {cls.selector_for(dev)} "
            f"({cls.describe(dev)})"
        )
        return cls(dev)

    def info(self) -> dict:
        """Best-effort USB facts about the selected device, for display in the UI
        and the ``/printer/info`` endpoint.

        Reads only descriptors (no claim required), and never raises —
        string-descriptor reads can fail on permissions or a busy device, in
        which case the field is simply ``None``.
        """
        dev = self.dev

        def _string(attr: str) -> Optional[str]:
            try:
                return usb.util.get_string(dev, getattr(dev, attr)) or None
            except Exception:
                return None

        try:
            ports = dev.port_numbers
            port_path = "-".join(str(n) for n in ports) if ports else None
        except Exception:
            port_path = None

        return {
            "vendor_id": f"{dev.idVendor:04x}",
            "product_id": f"{dev.idProduct:04x}",
            "selector": self.selector_for(dev),
            "bus": getattr(dev, "bus", None),
            "address": getattr(dev, "address", None),
            "port_path": port_path,
            "device_path": (
                f"/dev/bus/usb/{dev.bus:03d}/{dev.address:03d}"
                if getattr(dev, "bus", None) is not None
                and getattr(dev, "address", None) is not None
                else None
            ),
            "serial": _string("iSerialNumber"),
            "manufacturer": _string("iManufacturer"),
            "product": _string("iProduct"),
            "description": self.describe(dev),
            "known_vendor": KNOWN_TSPL_VENDORS.get(dev.idVendor),
        }

    @classmethod
    def list_usb_devices(cls) -> List[dict]:
        """Enumerate *all* connected USB devices for the settings picker, flagging
        the ones that look like a TSPL printer (``is_candidate``). Pure descriptor
        reads — nothing is claimed. Never raises: returns ``[]`` if libusb is
        unavailable. Candidates are listed first; duplicate ``vid:pid`` selectors
        are collapsed (the selector can't distinguish two identical models anyway).
        """
        try:
            found = _find(find_all=True)
        except Exception:
            return []
        if found is None:
            return []
        out: List[dict] = []
        seen: set[str] = set()
        for dev in found:
            try:
                selector = cls.selector_for(dev)
                if selector in seen:
                    continue
                seen.add(selector)
                out.append(
                    {
                        "selector": selector,
                        "description": cls.describe(dev),
                        "is_candidate": cls._matches(dev),
                    }
                )
            except Exception:
                continue
        out.sort(key=lambda d: (not d["is_candidate"], d["description"].lower()))
        return out

    # -------------------------
    # --- Lookup: VID / PID ---
    # -------------------------
    @classmethod
    def by_vendor_and_product_id(
        cls, vendor: Optional[int | str] = None, product: Optional[int | str] = None
    ) -> Self:
        if vendor is None and product is None:
            raise ValueError("Must specify vendor and/or product ID")

        # Convert hex strings
        if isinstance(vendor, str):
            vendor = int(vendor, 16)
        if isinstance(product, str):
            product = int(product, 16)

        devices = _find(
            find_all=True,
            idVendor=vendor if vendor is not None else None,
            idProduct=product if product is not None else None,
        )

        if devices is None:
            raise ValueError("No USB devices found matching given VID/PID")

        # Return the first match
        for dev in devices:
            return cls(dev)

        raise ValueError("No USB devices found matching given VID/PID")

    # -----------------------------
    # --- Lookup: Bus + Address ---
    # -----------------------------
    @classmethod
    def by_bus_and_device_id(
        cls, bus: Optional[int | str] = None, device_id: Optional[int | str] = None
    ) -> Self:
        if bus is None or device_id is None:
            raise ValueError("bus and device_id must both be provided")

        if isinstance(bus, str):
            bus = int(bus)
        if isinstance(device_id, str):
            device_id = int(device_id)

        for dev in _find(find_all=True):
            if dev.bus == bus and dev.address == device_id:
                return cls(dev)

        raise ValueError(f"No USB device found at bus={bus} device={device_id}")

    # -------------------------
    # --- Lookup: Serial#  ---
    # -------------------------
    @classmethod
    def by_serial(cls, serial: str) -> Self:
        if not serial:
            raise ValueError("Serial cannot be empty")

        for dev in _find(find_all=True):
            try:
                dev_serial = usb.util.get_string(dev, dev.iSerialNumber)
            except Exception:
                continue

            if dev_serial == serial:
                return cls(dev)

        raise ValueError(f"No USB device found with serial={serial}")

    # ----------------------------
    # --- Lookup: Port Path     ---
    # ----------------------------
    @classmethod
    def by_port(cls, port_path: List[int] | str) -> Self:
        """
        port_path may be:
            [3, 1, 2]
        or a string "3-1-2"
        """

        if isinstance(port_path, str):
            # Convert "3-1-2" → [3,1,2]
            port_path = [int(x) for x in port_path.split("-")]

        for dev in _find(find_all=True):
            if dev.port_numbers == port_path:
                return cls(dev)

        raise ValueError(f"No USB device found at port path {port_path}")

    # ----------------------------
    # --- Lookup: Device Path   ---
    # ----------------------------
    @classmethod
    def by_device_path(cls, device_path: str) -> Self:
        """
        Find device by kernel device path.

        device_path can be:
            "/dev/bus/usb/001/004"
        or just:
            "001/004"

        This extracts bus and device numbers from the path.
        """
        if not device_path:
            raise ValueError("Device path cannot be empty")

        # Handle full path or just "bus/device"
        if device_path.startswith("/dev/bus/usb/"):
            device_path = device_path.replace("/dev/bus/usb/", "")

        parts = device_path.split("/")
        if len(parts) != 2:
            raise ValueError(
                f"Invalid device path format: {device_path}. "
                "Expected format: '/dev/bus/usb/001/004' or '001/004'"
            )

        try:
            bus = int(parts[0])
            device_id = int(parts[1])
        except ValueError:
            raise ValueError(
                f"Invalid device path format: {device_path}. "
                "Bus and device must be numeric."
            )

        # Reuse the bus+device lookup
        return cls.by_bus_and_device_id(bus, device_id)

    # -----------------------------
    # --- Helper (Optional Use) ---
    # -----------------------------
    @staticmethod
    def find_device_by_bus_and_address(bus, address):
        for dev in _find(find_all=True):
            if dev.bus == bus and dev.address == address:
                return dev
        return None

    def __init__(
        self,
        usb_device: Device,
        retry_interval: float = 1.0,
    ) -> None:
        self.dev: Device = usb_device
        self.ep_out: Optional[Endpoint] = None
        self.ep_in: Optional[Endpoint] = None
        self.retry_interval: float = retry_interval

    # ---------------------------------------------------------
    #  Connect: claim the (already-discovered) device + endpoints
    # ---------------------------------------------------------
    def connect(self, max_retries: int = 5) -> bool:
        """
        Configure ``self.dev`` and resolve the bulk IN/OUT endpoints.

        The device itself is selected by the ``by_*`` class methods; this only
        sets up the USB configuration and endpoints so ``send``/``receive`` can
        talk to it. Retries a few times on transient USB errors.
        """
        if self.dev is None:
            raise RuntimeError("No USB device to connect to.")

        attempt = 0
        while True:
            try:
                # Detach any kernel drivers
                try:
                    if self.dev.is_kernel_driver_active(0):
                        self.dev.detach_kernel_driver(0)
                except Exception:
                    pass

                self.dev.set_configuration()
                cfg: Configuration = self.dev.get_active_configuration()
                intf: Interface = cfg[(0, 0)]

                # Resolve endpoints by direction
                self.ep_out = usb.util.find_descriptor(
                    intf,
                    custom_match=lambda e: usb.util.endpoint_direction(
                        e.bEndpointAddress
                    )
                    == usb.util.ENDPOINT_OUT,
                )

                self.ep_in = usb.util.find_descriptor(
                    intf,
                    custom_match=lambda e: usb.util.endpoint_direction(
                        e.bEndpointAddress
                    )
                    == usb.util.ENDPOINT_IN,
                )

                if not self.ep_out:
                    raise RuntimeError("USB OUT endpoint not found.")
                if not self.ep_in:
                    raise RuntimeError("USB IN endpoint not found.")

                print("Connected to TSPL printer.")
                return True

            except USBError as e:
                # Permission errors (EACCES) never resolve by retrying — fail fast
                # with a hint instead of looping and dumping a stack trace.
                if e.errno == 13:
                    raise PermissionError(
                        "Access denied opening the USB printer (EACCES). Grant USB "
                        "access via a udev rule (or run with sudo) — see the "
                        "'Printer setup' section of the README."
                    ) from e
                attempt += 1
                if attempt >= max_retries:
                    raise
                print(f"Connection error: {e}. Retrying ({attempt}/{max_retries})...")
                time.sleep(self.retry_interval)

            except Exception as e:
                attempt += 1
                if attempt >= max_retries:
                    raise
                print(f"Connection error: {e}. Retrying ({attempt}/{max_retries})...")
                time.sleep(self.retry_interval)

    def disconnect(self) -> None:
        """Release the USB device so another opener can claim it.

        Critical for the single-printer design: the worker *owns* the printer,
        but the status endpoints also open the device. If a status probe never
        releases it, the kernel keeps the interface claimed and every subsequent
        open (the worker's print, the next probe) fails with EBUSY ("Resource
        busy") — producing a retry flood. Always pair an open with a
        ``disconnect`` (try/finally).
        """
        if self.dev is None:
            return
        try:
            usb.util.dispose_resources(self.dev)
        except Exception:
            pass
        self.ep_out = None
        self.ep_in = None

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.disconnect()

    @staticmethod
    def _to_wire(cmd: str | bytes, raw: bool) -> bytes:
        """Encode a command for the USB OUT endpoint.

        ``raw=True`` sends the bytes exactly as given — required for real-time
        TSPL commands (e.g. ``<ESC>!?``) which must NOT be newline-terminated.
        """
        if raw:
            return cmd if isinstance(cmd, bytes) else cmd.encode("ascii")
        if isinstance(cmd, str):
            return (cmd.strip() + "\n").encode("ascii")
        return cmd.strip(b"\n") + b"\n"

    # ---------------------------------------------------------
    #  Send a TSPL command (auto reconnect if needed)
    # ---------------------------------------------------------
    def send(self, cmd: str | bytes, raw: bool = False) -> None:
        if self.ep_out is None:
            self.connect()

        data = self._to_wire(cmd, raw)

        try:
            self.ep_out.write(data)

        except usb.core.USBError:
            print("USB write failed — reconnecting...")
            self.connect()
            self.ep_out.write(data)

    # ---------------------------------------------------------
    #  Send multiple commands
    # ---------------------------------------------------------
    def send_many(
        self, commands: Union[List[str], tuple[str, ...]], raw: bool = False
    ) -> None:
        for c in commands:
            self.send(c, raw=raw)

    def receive(self, timeout: int = 1000, max_length: int = 1024) -> Optional[bytes]:
        """
        Read data from the TSPL printer via USB IN endpoint.

        Args:
            timeout: Timeout in milliseconds (default: 1000ms)
            max_length: Maximum number of bytes to read (default: 1024)

        Returns:
            bytes: Data received from the printer, or None if no data/error

        Raises:
            RuntimeError: If not connected or endpoint not available
        """
        if not self.dev:
            raise RuntimeError("Not connected to USB device. Call connect() first.")

        if not self.ep_in:
            raise RuntimeError("USB IN endpoint not available.")

        try:
            data = self.ep_in.read(max_length, timeout=timeout)
            return bytes(data)

        except usb.core.USBError as e:
            # Timeout or no data available
            if e.errno == 110:  # Timeout
                return None

            # Connection lost - attempt reconnect
            print(f"USB read failed: {e} — reconnecting...")
            try:
                self.connect()
                data = self.ep_in.read(max_length, timeout=timeout)
                return bytes(data)
            except Exception:
                return None

        except Exception as e:
            print(f"Receive error: {e}")
            return None

    def receive_string(
        self, timeout: int = 1000, max_length: int = 1024, encoding: str = "ascii"
    ) -> Optional[str]:
        """
        Read data from the TSPL printer and decode as string.

        Args:
            timeout: Timeout in milliseconds (default: 1000ms)
            max_length: Maximum number of bytes to read (default: 1024)
            encoding: Text encoding to use (default: 'ascii')

        Returns:
            str: Decoded string from printer, or None if no data/error
        """
        data = self.receive(timeout=timeout, max_length=max_length)

        if data is None:
            return None

        try:
            return data.decode(encoding).strip()
        except UnicodeDecodeError as e:
            print(f"Decode error: {e}")
            return None

    def query(
        self, cmd: str | bytes, timeout: int = 1000, max_length: int = 1024, raw: bool = False
    ) -> Optional[bytes]:
        self.send(cmd, raw=raw)
        time.sleep(0.1)  # Brief delay for printer to process
        return self.receive(timeout=timeout, max_length=max_length)

    def query_string(
        self, cmd: str, timeout: int = 1000, max_length: int = 1024
    ) -> Optional[str]:
        """
        Send a TSPL query command and wait for response.

        Args:
            cmd: TSPL command to send
            timeout: Timeout in milliseconds to wait for response
            max_length: Maximum response length

        Returns:
            str: Response from printer, or None if no response

        Example:
            >>> printer.query("~!T")  # Query printer status
            >>> printer.query("? DENSITY")  # Query density setting
        """
        self.send(cmd)
        time.sleep(0.1)  # Brief delay for printer to process
        return self.receive_string(timeout=timeout, max_length=max_length)
