# Тестирование

## Стратегия

- **Unit-тесты** не требуют БД и сети: парсер на HTML-фикстурах, форматирование,
  клавиатуры, условия алертов, загрузка фото, конфиг.
- **Интеграционные тесты** запускаются только при заданном `TEST_DATABASE_URL`
  и работают с настоящим PostgreSQL: репозитории, мониторинг, алерты, кулдаун.
- **CI** поднимает PostgreSQL 16, применяет миграции, запускает линтер, тесты
  и сборку Docker-образа.

## Запуск

```bash
pytest                                   # без БД, интеграционные скипаются
ruff check .
ruff format --check .

TEST_DATABASE_URL="postgresql+asyncpg://funpay:funpay@localhost:5432/funpay" pytest
```

Интеграционные тесты создают схему в указанной базе и удаляют её после прогона.
Не направляйте `TEST_DATABASE_URL` на базу с нужными данными.

## Что покрыто

| Область | Тесты |
|---|---|
| Парсер | `tests/test_parser.py`, фикстуры FunPay |
| HTTP-клиент | `tests/test_http.py` |
| Модели и миграции | `tests/test_models.py` |
| Репозитории | `tests/test_repositories.py` (интеграционные) |
| Мониторинг | `tests/test_monitoring.py` (интеграционные) |
| Алерты | `tests/test_alerts.py` (unit + интеграционные) |
| Бот | `tests/test_bot*.py`, `tests/test_admin.py` |
| Графики | `tests/test_charts.py` |
| VK | `tests/test_vk_upload.py`, `tests/test_alert_notifier.py` |

## CI

`.github/workflows/ci.yml`:

1. сервис `postgres:16-alpine` с healthcheck;
2. `pip install -e ".[dev]"`;
3. `alembic upgrade head`;
4. `ruff check .` и `ruff format --check .`;
5. `pytest`;
6. `docker build .`.

Локально Docker может быть недоступен — тогда интеграционные тесты скипаются,
а полный прогон выполняет CI.
