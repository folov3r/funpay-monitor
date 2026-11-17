# Тестирование

## Стратегия

- **Unit-тесты** не требуют БД и сети: парсер на HTML-фикстурах, форматирование,
  клавиатуры, условия алертов, загрузка фото, конфиг.
- **SQLite-тесты** проверяют кросс-базовые типы, PRAGMA, репозитории и агрегации
  на временной базе в памяти или во временном каталоге.
- **Тесты локального API** поднимают FastAPI с SQLite и подменённым парсером:
  категории, история, подписки, уведомления, reparse.
- **Интеграционные тесты PostgreSQL** запускаются только при заданном
  `TEST_DATABASE_URL` и относятся к оставшемуся VK-каналу.
- **CI** поднимает PostgreSQL 16, применяет миграции, запускает линтер, тесты,
  сборку Docker-образа и сборку фронтенда.

## Запуск

```bash
pytest                                   # без внешней БД, интеграционные скипаются
ruff check .
ruff format --check .

TEST_DATABASE_URL="postgresql+asyncpg://funpay:funpay@localhost:5432/funpay_test" pytest
```

Без PostgreSQL проходят 192 теста, 29 интеграционных скипаются. Интеграционные
тесты создают схему в указанной базе и удаляют её после прогона. Не направляйте
`TEST_DATABASE_URL` на базу с нужными данными: используйте отдельную
`funpay_test`.

Фронтенд проверяется отдельно:

```bash
cd frontend
npm run typecheck
npm run build
```

## Что покрыто

| Область | Тесты |
|---|---|
| Парсер | `tests/test_parser.py`, фикстуры FunPay |
| HTTP-клиент | `tests/test_http.py` |
| Модели и миграции | `tests/test_models.py` |
| Типы и PRAGMA SQLite | `tests/test_db_types.py` |
| Репозитории | `tests/test_repositories.py` (PostgreSQL), `tests/test_repositories_sqlite.py` |
| Локальный API | `tests/test_api.py` |
| Запуск ядра | `tests/test_desktop.py` |
| Мониторинг | `tests/test_monitoring.py` (интеграционные) |
| Алерты | `tests/test_alerts.py` (unit + интеграционные) |
| Бот | `tests/test_bot*.py`, `tests/test_admin.py` |
| Графики | `tests/test_charts.py` |
| VK | `tests/test_vk_upload.py`, `tests/test_alert_notifier.py` |

## CI

`.github/workflows/ci.yml`:

1. сервис `postgres:16-alpine` с healthcheck;
2. `pip install -e ".[dev,docs]"`;
3. `alembic upgrade head`;
4. `ruff check .` и `ruff format --check .`;
5. `pytest`;
6. `docker build .`;
7. отдельный job `frontend`: `npm ci` и `npm run build`.

`.github/workflows/release.yml` запускается по тегу `v*` и собирает установщики
Windows и Linux на соответствующих runner'ах.
