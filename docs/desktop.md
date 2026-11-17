# Десктоп-приложение

Основная сборка FunPay Monitor — настольная программа. Окно Tauri запускает
Python-ядро, ядро поднимает локальный API и работает с SQLite. Тот же
фронтенд открывается в браузере по адресу `http://127.0.0.1:8765`.

## Компоненты

| Компонент | Технология | Назначение |
|---|---|---|
| Окно | Tauri 2 + Rust | окно, трей, запуск и остановка ядра |
| Интерфейс | React + TypeScript + ECharts | категории, подписки, графики, журнал |
| Ядро | Python 3.12 + FastAPI | парсинг, планировщик, алерты, API |
| База | SQLite через SQLAlchemy | категории, предложения, история, подписки |

Фронтенд не знает, где он открыт: в dev-режиме он обращается к `/api` через
прокси Vite, в окне Tauri — к `http://127.0.0.1:8765/api`.

## Запуск

```
Tauri setup
  └── spawn funpay-monitor-core (sidecar)
        └── uvicorn 127.0.0.1:8765
              ├── FastAPI routes
              ├── APScheduler (parse job)
              └── SQLite
```

- В установленной программе рядом с исполняемым файлом лежит
  `funpay-monitor-core` (Windows: `.exe`).
- В dev-режиме, если sidecar не собран, Tauri запускает
  `.venv/bin/python -m app.desktop` из корня репозитория.
- Переменная `FUNPAY_CORE_BIN` задаёт путь к ядру вручную,
  `FUNPAY_PYTHON` — интерпретатор для dev-режима.
- Закрытие окна скрывает его в трей. Пункт «Выход» завершает ядро.

## Локальный API

Префикс — `/api`, порт по умолчанию `8765`. Основные маршруты:

| Метод | Путь |
|---|---|
| `GET` | `/api/health` |
| `GET` | `/api/status` |
| `GET` | `/api/categories` |
| `POST` | `/api/categories/import` |
| `GET` | `/api/categories/{id}/summary` |
| `GET` | `/api/categories/{id}/offers` |
| `GET` | `/api/categories/{id}/history` |
| `POST` | `/api/categories/{id}/reparse` |
| `GET` / `POST` | `/api/subscriptions` |
| `DELETE` | `/api/subscriptions/{id}` |
| `GET` | `/api/subscriptions/{id}/stats` |
| `GET` | `/api/notifications` |

Swagger доступен по адресу `http://127.0.0.1:8765/docs`. API слушает только
loopback-интерфейс.

## Уведомления

`DesktopAlertNotifier` показывает системное уведомление и пишет запись в
таблицу `notifications`:

- Windows — через пакет `winotify`;
- Linux — через `notify-send`;
- если системный канал недоступен, уведомление остаётся в журнале
  приложения.

Графики для уведомлений не рендерятся: desktop-ядро не включает matplotlib.
Это уменьшает размер сборки и ускоряет доставку алертов.

## Данные

| ОС | Путь |
|---|---|
| Windows | `%APPDATA%\com.funpaymonitor.desktop\funpay-monitor.sqlite3` |
| Linux | `~/.local/share/com.funpaymonitor.desktop/funpay-monitor.sqlite3` |

При запуске `python -m app.desktop` без Tauri используется каталог
`funpay-monitor` в `XDG_DATA_HOME` или `%APPDATA%`. Переопределение —
`FUNPAY_DATA_DIR` или `--data-dir`.

## Сборка установщика

```bash
pip install -e ".[build]"
python scripts/build_core.py
cd frontend
npm run tauri:build
```

`scripts/build_core.py`:

1. собирает фронтенд, если `frontend/dist` отсутствует;
2. запускает PyInstaller в режиме `--onefile`;
3. исключает matplotlib, numpy, vkbottle и код VK-бота;
4. встраивает `frontend/dist`, чтобы ядро могло отдать веб-интерфейс;
5. копирует файл в `frontend/src-tauri/binaries/funpay-monitor-core-<triple>`.

Tauri добавляет sidecar через `tauri.release.conf.json`
(`bundle.externalBin`) и кладёт его рядом с исполняемым файлом.

Сборка выполняется на целевой ОС: Windows-пакет — на Windows, Linux-пакет —
на Linux. Результат — в `frontend/src-tauri/target/release/bundle/`.

При публикации тега `v*` workflow `.github/workflows/release.yml` собирает
установщики для обеих систем: Windows — `.msi` и `.exe`, Linux — `.deb` и
`.AppImage`. По тегу создаётся GitHub Release с этими файлами.

## Разработка

```bash
python -m app.desktop          # только ядро и браузерный интерфейс
cd frontend && npm run dev     # Vite с прокси на 127.0.0.1:8765
cd frontend && npm run tauri dev
```

Проверки:

```bash
pytest
ruff check .
ruff format --check .
cd frontend && npm run typecheck && npm run build
```

## Ограничения

- один экземпляр приложения на порт `8765`;
- sidecar собирается только под текущую ОС;
- автоматических обновлений нет;
- при изменении вёрстки FunPay парсер возвращает ошибку, она видна во
  вкладке «Состояние».
