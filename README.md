# Telegram Reseller Management Bot for Marzban

A production-oriented Telegram bot for managing Marzban resellers with balance accounting, reseller-specific pricing, recharge approvals, and automated reports. The bot uses the Marzban REST API for all panel operations and stores reseller/accounting data in SQLAlchemy-managed database tables.

## Features

- Admin reseller management: add, enable/disable/archive-ready data model, edit-ready repository layer.
- Balance management with immutable transaction history.
- Reseller dashboard with balance, price per GB, account status, and created-user count.
- Conversation-driven user creation and renewal with validation, confirmation, rollback-safe billing, Back/Cancel controls, and user-friendly errors.
- Top-up requests with image/text receipt delivery to admins and approve/reject inline actions.
- Maintenance mode that blocks non-admin users.
- Marzban inbound retrieval service and database-backed inbound permission model.
- Persian/Jalali reports using Asia/Tehran timezone.
- Alembic migrations and SQLite default database, designed for MySQL/PostgreSQL migration.
- Typed, modular Python 3.12+ code using aiogram 3.x and SQLAlchemy 2.x.

## Architecture

The codebase follows a layered architecture:

- **Handlers** receive Telegram updates and orchestrate flows.
- **Repositories** encapsulate database access.
- **Services** contain business logic such as billing, Marzban API access, validation, reporting, and date formatting.
- **Middlewares** enforce authentication and maintenance mode.
- **States** define aiogram FSM conversations.
- **Keyboards** keep UI construction separate from logic.

## Installation

```bash
git clone <your-repo-url>
cd resell-bot
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Configuration

Edit `.env`:

```env
BOT_TOKEN=123456:telegram-token
ADMIN_IDS=123456789,987654321
MARZBAN_BASE_URL=https://panel.example.com
MARZBAN_USERNAME=admin
MARZBAN_PASSWORD=secret
DATABASE_URL=sqlite+aiosqlite:///bot.db
TIMEZONE=Asia/Tehran
DEFAULT_LANGUAGE=en
LOG_LEVEL=INFO
```

### Environment variables

| Variable | Description |
| --- | --- |
| `BOT_TOKEN` | Telegram bot token from BotFather. |
| `ADMIN_IDS` | Comma-separated Telegram numeric admin IDs. |
| `MARZBAN_BASE_URL` | Marzban panel base URL without a trailing slash. |
| `MARZBAN_USERNAME` | Marzban admin username. |
| `MARZBAN_PASSWORD` | Marzban admin password. |
| `DATABASE_URL` | SQLAlchemy database URL. Defaults to SQLite async. |
| `TIMEZONE` | Application timezone, default `Asia/Tehran`. |
| `DEFAULT_LANGUAGE` | Reserved default language setting. |
| `LOG_LEVEL` | Python logging level. |

## Running locally

```bash
alembic upgrade head
python run.py
```

## Database migrations

Create a new migration after model changes:

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

The first migration creates:

- `resellers`
- `balance_transactions`
- `recharge_requests`
- `reseller_inbounds`
- `created_users`
- `bot_settings`
- `operation_logs`

## Folder structure

```text
app/
  config.py
  main.py
  database/
    models.py
    repositories.py
    session.py
  handlers/
    admin.py
    common.py
    reseller.py
  keyboards/
    admin.py
    common.py
    reseller.py
  middlewares/
    auth.py
    maintenance.py
  services/
    billing.py
    datetime.py
    marzban.py
    reports.py
    validators.py
  states/
    admin.py
    reseller.py
  utils/
    logger.py
alembic/
  versions/
README.md
requirements.txt
.env.example
run.py
```

## Marzban API integration

`app/services/marzban.py` authenticates through `/api/admin/token` and uses bearer-token requests for:

- `GET /api/inbounds`
- `GET /api/user/{username}`
- `POST /api/user`
- `PUT /api/user/{username}`

Requests include basic retry handling for transient server-side failures. If a Marzban create/renew request fails, billing is not committed because database changes happen only after the API call succeeds inside the transactional flow.

## Telegram usage

### Conversation-driven admin panel

Admins start with `/start` and manage the bot from the inline Telegram UI. The admin does not need to memorize long slash commands: every operation is available through buttons, step-by-step prompts, validation messages, Back/Cancel controls, and a confirmation screen before anything is saved.

The admin panel supports:

- Add Reseller: collect Telegram ID, initial balance, price per GB, and display name, then confirm creation.
- Edit Reseller: update display name, price per GB, or status through guided prompts.
- Edit Balance: increase, decrease, or set a reseller balance after confirmation.
- Maintenance Mode: view current ON/OFF status and enable or disable it from buttons.
- Inbound Permissions: select a reseller, allow all inbounds by default, or toggle custom inbound tags one by one before saving.
- Transactions: select a reseller, filter recent transactions, and paginate through results.
- Recharge Moderation: approve or reject recharge requests from inline buttons, with confirmation and a rejection-reason conversation.

Slash commands such as `/add_reseller` and `/maintenance` are retained only as shortcuts into the guided conversations; they are not required for normal administration. Recharge approvals are handled with inline buttons sent to admins.

### Reseller flow

Resellers use `/start` to open the dashboard and can:

- Create user
- Renew user
- Request balance
- View help entry point

Usernames are validated with:

```regex
^[a-z0-9_]+$
```

## Screenshots

> Add screenshots here after deploying the bot.

- Admin panel screenshot placeholder
- Reseller dashboard screenshot placeholder
- Create-user confirmation screenshot placeholder
- Recharge approval screenshot placeholder

## Backup instructions

For SQLite deployments:

```bash
sqlite3 bot.db ".backup 'backup-$(date +%F).db'"
```

Also back up `.env` securely outside the repository and never commit secrets.

For PostgreSQL/MySQL, use the provider-native backup utilities such as `pg_dump` or `mysqldump` and schedule automated encrypted backups.

## Migration to MySQL/PostgreSQL

The project uses SQLAlchemy models and Alembic migrations to keep migration simple.

1. Install the appropriate async driver, for example `asyncpg` or `asyncmy`.
2. Change `DATABASE_URL`, for example:
   - `postgresql+asyncpg://user:pass@host:5432/dbname`
   - `mysql+asyncmy://user:pass@host:3306/dbname`
3. Run `alembic upgrade head`.
4. Import or migrate existing SQLite data with a controlled ETL script.

## Troubleshooting

- **Bot does not start:** verify `BOT_TOKEN` and `ADMIN_IDS` are set.
- **Marzban authentication fails:** verify URL, username, password, SSL, and panel availability.
- **Database errors:** run `alembic upgrade head` and check `DATABASE_URL`.
- **Admins do not receive reports:** verify the admin has started the bot and the Telegram ID is numeric and listed in `ADMIN_IDS`.
- **Reseller blocked:** check reseller status and maintenance mode.

## Future roadmap

- Role-based admin permissions.
- Multi-language message catalog.
- Background synchronization with Marzban.
- Exportable CSV/Excel accounting reports.
- Docker Compose deployment profile.
