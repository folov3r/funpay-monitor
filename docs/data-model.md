# Модель данных

Восемь таблиц PostgreSQL, описанных в `app/db/models.py`. Миграции — Alembic.

## Связи

```
users 1 ─── * subscriptions * ─── 1 categories
                    │                    │
                    │                    └── 1 ─── * servers
                    │                                   │
                    └── 1 ─── * notifications           │
                                        │               │
                                        └── 1 price_snapshots
                                                            │
categories 1 ─── * offers ─── 1 servers                     │
categories 1 ─── * parse_runs                               │
categories 1 ─── * price_snapshots ─── 1 servers ───────────┘
```

## users

Пользователи бота.

| Поле | Тип | Описание |
|---|---|---|
| `id` | bigint PK | внутренний id |
| `vk_id` | bigint unique | id пользователя VK |
| `first_name` | varchar(255) | имя, если пришло |
| `is_admin` | boolean | зарезервировано; доступ к админке задаётся `VK_ADMIN_IDS` |
| `created_at` | timestamptz | дата регистрации |

## categories

Отслеживаемые категории FunPay.

| Поле | Тип | Описание |
|---|---|---|
| `funpay_id` | integer | id из URL (`/chips/30/` → 30) |
| `type` | varchar(16) | `chip` или `lot` |
| `title` | varchar(255) | название с сайта |
| `game_title` | varchar(255) | игра, если определилась |
| `url_path` | varchar(255) | нормализованный путь `/chips/30/` |
| `server_label` | varchar(64) | подпись поля выбора с FunPay: «Сервер», «Способ передачи»; `NULL` — поля нет |
| `is_active` | boolean | участвует ли в расписании |
| `last_parsed_at` | timestamptz | последний успешный разбор |

Уникальность: `(funpay_id, type)`.

## servers

Серверы/реалмы внутри категории.

| Поле | Тип | Описание |
|---|---|---|
| `category_id` | bigint FK | категория |
| `funpay_server_id` | integer | id сервера; `0` — «Любой» |
| `name` | varchar(255) | отображаемое имя |

Уникальность: `(category_id, funpay_server_id)`.

## offers

Текущие предложения категории. Полностью перезаписываются при каждом разборе.

| Поле | Тип | Описание |
|---|---|---|
| `category_id`, `server_id` | FK | принадлежность |
| `seller_id`, `seller_name` | bigint, varchar | продавец |
| `amount` | numeric(18,2) | количество (`кк` × 1 000 000) |
| `price` | numeric(18,6) | цена лота |
| `currency` | varchar(8) | по умолчанию RUB |
| `item_type` | varchar(64) nullable | тип предложения, нижний регистр |
| `method` | varchar(64) nullable | способ получения с FunPay |
| `title` | text nullable | название предмета для поиска |
| `is_online`, `is_promo` | boolean | флаги продавца и промо |
| `parsed_at` | timestamptz | время записи |

Индексы: `(category_id, server_id, price)` и
`(category_id, item_type, price)`.

## price_snapshots

История цен — основа графиков и алертов.

| Поле | Тип | Описание |
|---|---|---|
| `category_id`, `server_id` | FK | принадлежность |
| `item_type` | varchar(64) nullable | срез по типу предложения |
| `query` | varchar(255) nullable | срез по названию, нижний регистр |
| `min_price` | numeric(18,6) | минимум по срезу |
| `median_price` | numeric(18,6) | медиана по срезу |
| `offer_count` | integer | число офферов |
| `captured_at` | timestamptz | время снапшота |

Снапшоты одного прогона получают одинаковый `captured_at`, потому что PostgreSQL
`now()` фиксируется на транзакцию. Это используется для агрегации категории.

Для каждой категории всегда пишутся базовые снапшоты с `item_type IS NULL` и
`query IS NULL`. Дополнительно создаются снапшоты для срезов активных подписок:
тип и/или название. Поэтому `NULL` в фильтре означает «базовый срез», а не
«любой срез».

Индекс: `(category_id, server_id, item_type, query, captured_at)`.

## parse_runs

Журнал запусков парсера.

| Поле | Тип | Описание |
|---|---|---|
| `category_id` | FK | категория |
| `started_at`, `finished_at` | timestamptz | границы запуска |
| `status` | varchar(16) | `running`, `ok`, `error`, `partial` |
| `offers_found` | integer | сколько офферов нашли |
| `error_text` | text | текст ошибки |

## subscriptions

Правила алертов.

| Поле | Тип | Описание |
|---|---|---|
| `user_id`, `category_id` | FK | кому и за чем следить |
| `server_id` | FK nullable | `NULL` — любой сервер |
| `item_type` | varchar(64) nullable | тип предложения, `NULL` — все |
| `query` | varchar(255) nullable | часть названия, `NULL` — без поиска |
| `mode` | varchar(16) | `abs`, `pct`, `lowest` |
| `threshold` | numeric(18,6) nullable | порог в рублях или процентах |
| `is_active` | boolean | мягкое удаление |
| `created_at` | timestamptz | дата создания |

Подписки различаются по `(user, category, server, mode, item_type, query)`,
поэтому в одной категории можно отдельно следить за предметами, услугами и
конкретным названием.

## notifications

Журнал отправленных алертов и основа кулдауна.

| Поле | Тип | Описание |
|---|---|---|
| `subscription_id`, `snapshot_id` | FK | подписка и снимок |
| `sent_at` | timestamptz | время отправки |
| `price` | numeric(18,6) | цена на момент алерта |
| `reason` | varchar(16) | `abs`, `pct`, `lowest` |

Перед отправкой проверяется последний `sent_at` по подписке: если прошло меньше
`ALERT_COOLDOWN_HOURS`, уведомление пропускается.
