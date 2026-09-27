"""HTTP-клиент для взаимодействия с LabelJetty на ноуте.

В dev-режиме (PRINTER_URL не задан) сохраняет TSPL в локальный файл.
В prod-режиме отправляет POST на /api/print/raw нашего форка LabelJetty.
"""

import os
from datetime import datetime

import httpx

PRINTED_DIR = "/app/printed"
PRINTER_URL = os.getenv("PRINTER_URL", "").strip()
PRINTER_TIMEOUT = float(os.getenv("PRINTER_TIMEOUT", "15.0"))


def send_to_printer(tspl: str, profile: str = "75x120") -> dict:
    """
    Отправляет готовый TSPL на принтер.

    :param tspl: полная TSPL-программа (включая финальный PRINT)
    :param profile: имя профиля этикетки ('75x120' или '58x40')
    :return: dict с полями mode, status, детали
    """
    if not PRINTER_URL:
        return _save_to_file(tspl)
    return _send_http(tspl, profile)


def _send_http(tspl: str, profile: str) -> dict:
    try:
        r = httpx.post(
            f"{PRINTER_URL}/api/print/raw",
            json={"tspl": tspl, "profile_name": profile},
            timeout=PRINTER_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        return {
            "mode": "http",
            "status": "queued",
            "labeljetty_job_id": data.get("id"),
        }
    except httpx.HTTPStatusError as e:
        return {
            "mode": "http",
            "status": "error",
            "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}",
        }
    except httpx.HTTPError as e:
        return {"mode": "http", "status": "error", "error": str(e)}


def _save_to_file(tspl: str) -> dict:
    os.makedirs(PRINTED_DIR, exist_ok=True)
    filename = f"box_{datetime.now():%Y%m%d_%H%M%S_%f}.tspl"
    filepath = os.path.join(PRINTED_DIR, filename)
    with open(filepath, "w", encoding="cp1251", errors="replace") as f:
        f.write(tspl)
    return {"mode": "file", "status": "saved", "path": filepath}