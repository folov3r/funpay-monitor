# Быстрый старт

## Требования

- Docker и Docker Compose;
- сообщество VK с включёнными сообщениями и Long Poll API;
- ключ доступа сообщества.

## Настройка VK

1. Создайте сообщество или используйте существующее.
2. «Управление» → «Сообщения сообщества»: включите сообщения.
3. «Управление» → «Работа с API» → «Long Poll API»: включите и выберите версию.
4. Создайте ключ доступа сообщества с правами на сообщения.
5. Узнайте ID сообщества и ID своего пользователя VK для админ-команд.

> Заполняйте именно `.env`, а не `.env.example`: шаблон лежит в git и не должен
> содержать реальных токенов.

Пользователь должен написать сообществу первым: VK не разрешает сообществу
инициировать диалог.

Проверка ключа без запуска бота:

```bash
python scripts/check_vk.py
```

Скрипт выводит название сообщества, Long Poll сервер и число админов.

## Запуск через Docker

```bash
cp .env.example .env
# заполните VK_GROUP_TOKEN, VK_GROUP_ID и VK_ADMIN_IDS
docker compose up --build -d
docker compose logs -f bot worker
```

`docker compose` поднимает:

- `db` — PostgreSQL 16;
- `migrate` — применяет `alembic upgrade head` и завершается;
- `bot` — Long Poll обработчик команд;
- `worker` — планировщик парсинга и отправки алертов.

### Если Docker недоступен: Podman

```bash
sudo pacman -S podman
systemctl --user enable --now podman.socket
podman compose up --build -d
podman compose logs -f bot worker
```

Compose-файл менять не нужно: `podman compose` использует установленный
`docker-compose` как провайдер и сам подключает его к сокету Podman. Порт `5432`
должен быть свободен.

## Переменные окружения

| Переменная | Обязательна | По умолчанию | Описание |
|---|---|---|---|
| `VK_GROUP_TOKEN` | да | — | Ключ доступа сообщества |
| `VK_GROUP_ID` | нет | `0` | ID сообщества |
| `VK_ADMIN_IDS` | нет | — | VK id админов через запятую |
| `DATABASE_URL` | нет | локальный DSN | Подключение к PostgreSQL |
| `LOG_LEVEL` | нет | `INFO` | Уровень логов |
| `PARSE_INTERVAL_MINUTES` | нет | `15` | Интервал парсинга |
| `REQUEST_DELAY_SECONDS` | нет | `3` | Пауза между запросами к FunPay |
| `ALERT_COOLDOWN_HOURS` | нет | `6` | Кулдаун алертов на подписку |

## Локальная разработка

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

docker compose up -d db   # или podman compose up -d db
alembic upgrade head

pytest
ruff check .
python -m app.main     # бот
python -m app.worker   # воркер, в отдельном терминале
```

Если контейнеры недоступны, подойдёт локальный PostgreSQL 16: создайте базу,
укажите её в `DATABASE_URL`, примените `alembic upgrade head` и запустите оба
процесса. Воркер и бот общаются только через PostgreSQL, поэтому контейнеры не
обязательны.

## Первая подписка

1. Напишите боту `/start`.
2. Пришлите ссылку, например `https://funpay.com/chips/30/`.
3. Выберите сервер, режим и порог.
4. Проверьте `/list` и `/stats <id>`.
5. Дождитесь следующего прогона воркера или используйте `/reparse` (админ).
