# Развёртывание

## Ноутбук / локальная машина

```bash
cp .env.example .env
docker compose up --build -d
```

При работе от батареи отключите сон или используйте `systemd-inhibit`, иначе
воркер перестанет парсить и алерты не придут.

## Podman вместо Docker

Podman подходит как замена Docker: он работает без демона и может запускаться
rootless. Текущий `docker-compose.yml` совместим с Compose Spec, поэтому менять
его не нужно.

```bash
sudo pacman -S podman
systemctl --user enable --now podman.socket
podman compose up --build -d
podman compose ps
podman compose logs -f bot worker
```

`podman compose` — обёртка над внешним провайдером. Если установлен
`docker-compose`, используется он; Podman сам направляет его на свой сокет.
Предупреждение о запуске внешней команды — нормальное.

Остановка и удаление данных:

```bash
podman compose down
podman compose down -v   # вместе с томом PostgreSQL
```

Важно:

- порт `5432` должен быть свободен; локальный PostgreSQL нужно остановить или
  поменять порт в compose-файле;
- `restart: unless-stopped` работает, пока жив процесс Podman, но не включает
  автозапуск после перезагрузки. Для продакшена сгенерируйте systemd user unit
  (`podman generate systemd`) или используйте Quadlet;
- если `docker-compose` не установлен, поставьте `podman-compose` и укажите
  провайдер через `PODMAN_COMPOSE_PROVIDER=podman-compose`. Предпочтителен
  `docker-compose`: он полностью поддерживает `depends_on.condition` и
  `env_file` с `required: false`.

## VPS

1. Установите Docker и Docker Compose.
2. Скопируйте репозиторий и `.env`.
3. Запустите `docker compose up --build -d`.
4. Проверьте `docker compose ps` и логи `bot`/`worker`.

Контейнеры `bot` и `worker` имеют `restart: unless-stopped`, поэтому переживают
перезагрузку хоста. `migrate` выполняется один раз при старте и завершает работу.

## Обновление

```bash
git pull
docker compose up --build -d
```

Миграции применяются сервисом `migrate` до запуска бота и воркера.

## Резервные копии

MVP не содержит автоматического бэкапа. Для защиты истории цен:

```bash
docker compose exec -T db pg_dump -U funpay funpay > backup.sql
```

Рекомендуется cron-задача и хранение дампов вне сервера.

## Мониторинг

- `docker compose logs -f worker` — прогоны и ошибки парсинга;
- `/status` в боте — сводка и последние запуски;
- таблица `parse_runs` — история ошибок с текстом.

Внешний мониторинг (Uptime Kuma, healthchecks) в MVP не подключён.

## Переменные продакшена

- смените пароль PostgreSQL по умолчанию;
- не коммитьте `.env`;
- `LOG_LEVEL=INFO`, при отладке — `DEBUG`;
- интервал парсинга не меньше 15 минут;
- при нескольких воркерах потребуется блокировка задач, в MVP запускается один.
