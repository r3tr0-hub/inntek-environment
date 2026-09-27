# INNTEK ENVIRONMENT

Внутренняя система автоматизации производства курьерских пакетов.
Локальный сервер на предприятии + набор модулей: этикетки, контроль качества,
планирование, отчётность.

## Архитектура

```
┌──────────────────────────┐         ┌──────────────────────────┐
│  СЕРВЕР (Docker)         │         │  НОУТ с принтером        │
│  - PostgreSQL            │  HTTP   │  - LabelJetty (форк)     │
│  - FastAPI (backend)     │ ─────>  │  - USB ──> TSC TE200     │
└──────────────────────────┘         └──────────────────────────┘
```

- **backend/** — FastAPI-приложение, справочники, генерация TSPL.
- **printer_service/** — форк [LabelJetty](https://github.com/motey/LabelJetty) (MIT),
  ставится на ноут рядом с принтером. Подробности — в
  `printer_service/README-INNTEK.md`.

## Развёртывание на новом устройстве

### 1. Установить

- Docker Desktop — https://www.docker.com/products/docker-desktop/
- (только для устройства с принтером) Python 3.12 + labeljetty

### 2. Склонировать репозиторий

```powershell
cd C:\Projects
git clone https://github.com/<логин>/inntek-environment.git
cd inntek-environment
```

### 3. Создать `.env`

```powershell
copy .env.example .env
```

Открыть `.env`, вписать реальные значения:
- `POSTGRES_PASSWORD` — придумать надёжный.
- `JWT_SECRET` — случайная строка 32+ символа (можно `openssl rand -hex 32`).
- `PRINTER_URL` — `http://<ip-ноута>:8888`, если печатаем на принтер.
  Оставить пустым — TSPL будет писаться в файл `backend/printed/`.

### 4. Запустить

```powershell
docker compose up --build -d
```

### 5. Проверить

- http://localhost:8000/ — должно быть `{"service":"INNTEK ENVIRONMENT","status":"ok"}`
- http://localhost:8000/docs — Swagger, интерактивная документация.

## Ежедневный цикл работы

**Утром — забрать свежее:**

```powershell
git pull
```

**Вечером — сохранить:**

```powershell
git add .
git commit -m "что сделал за день"
git push
```

Или в VS Code: значок ветки в боковой панели → кнопка «Sync Changes».

## Что НЕ попадает в git

- `.env` — там пароли.
- `backend/printed/` — временные TSPL.
- `printer_service/.venv/`, `printer_service/images/`,
  `printer_service/*.sqlite` — локальные данные LabelJetty.
- Кеши Python и прочий мусор.

Полный список — в `.gitignore`.

## Статус модулей

| Модуль | Статус |
|---|---|
| Справочники (спецификации, пользователи, смены) | ✅ работает |
| Модуль этикеток на коробку | ✅ работает (печать через LabelJetty) |
| Прогон печати (партия N этикеток) | ⏳ следующий этап |
| Авторизация смены с составом | ⏳ в плане |
| Второй принтер (58×40) | ⏳ в плане |
| Модуль паллет | ⏳ в плане |
| Отчёты, контроль качества, склад | ⏳ в плане |

## Контакты

Внутренний проект. Вопросы — к инженеру-механику.