# Форк LabelJetty для INNTEK ENVIRONMENT

Это форк [LabelJetty](https://github.com/motey/LabelJetty) (MIT License),
доработанный под наши задачи. Установлен на ноутбуке рядом с принтером
TSC TE200 (Windows).

## Отличия от upstream

1. **Патч шрифта под Windows** (`src/labeljetty/printer/tspl.py`, ~строка 8):
   `DEFAULT_FONT_PATH` выбирается по `sys.platform` — на Windows это
   `C:/Windows/Fonts/arialbd.ttf`, иначе прежний Linux-путь.

2. **Эндпоинт `POST /api/print/raw`** (`src/labeljetty/web/api.py`):
   принимает готовые TSPL-команды от нашего backend.
   Тело запроса: `{"tspl": "...", "profile_name": "75x120"}`.
   Пре-валидация: символы должны укладываться в cp1251, иначе 400.

3. **JobType `"raw"`** (`src/labeljetty/printer/tspl.py`):
   добавлен в `Literal` для поддержки диспетчеризации в воркере.

4. **Метод `print_raw_tspl()`** (`src/labeljetty/printer/tspl.py`):
   кодирует TSPL в cp1251 и отправляет через `connection.send(raw=True)`.

5. **Обработка `"raw"`** (`src/labeljetty/service/worker.py`, `_dispatch`).

6. **Профили этикеток в `.env`**: 75x120 и 58x40.

## Установка на новом ноуте

1. Установить Python 3.12.
2. Установить драйвер libusb через Zadig (Options → List All Devices,
   драйвер libusb-win32).
3. `pip install -e .` из папки `printer_service/` (или `py -3.12 -m pip install -e .`).
4. Создать `.env` (по образцу, VID/PID подставить свои).
5. Запустить: `py -3.12 -m labeljetty`.
6. Проверить: `http://localhost:8888/`.
7. Настроить автозапуск через NSSM или Планировщик задач.

## Обновление

**НЕ** обновлять через `pip install --upgrade labeljetty` — потеряете патчи.
Только вручную: слить изменения upstream вручную или переносить патчи заново.

## Лицензия

MIT, оригинальный `LICENSE` сохранён в корне.