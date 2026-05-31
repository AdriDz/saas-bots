"""
Capa de base de datos del orquestador.

Tres tablas:
  - customers      → cada cliente que paga
  - subscriptions  → estado de pago de cada cliente
  - bot_instances  → bots desplegados (uno por cliente)
"""
import asyncpg
from datetime import datetime

from . import config

_pool: asyncpg.Pool | None = None


async def init():
    """Crea el pool de conexiones y las tablas si no existen."""
    global _pool
    _pool = await asyncpg.create_pool(config.DATABASE_URL)
    async with _pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id              SERIAL PRIMARY KEY,
                telegram_id     BIGINT UNIQUE,
                email           TEXT,
                stripe_customer TEXT UNIQUE,
                created_at      TIMESTAMPTZ DEFAULT now()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id               SERIAL PRIMARY KEY,
                customer_id      INTEGER REFERENCES customers(id),
                stripe_sub       TEXT UNIQUE,
                status           TEXT,            -- active | past_due | canceled
                failed_payments  INTEGER DEFAULT 0,
                current_period_end TIMESTAMPTZ,
                updated_at       TIMESTAMPTZ DEFAULT now()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_instances (
                id              SERIAL PRIMARY KEY,
                customer_id     INTEGER REFERENCES customers(id),
                bot_username    TEXT,
                bot_token       TEXT,            -- token del bot del cliente
                railway_project TEXT,
                railway_service TEXT,
                railway_env     TEXT,
                status          TEXT,            -- provisioning | active | paused | error
                created_at      TIMESTAMPTZ DEFAULT now(),
                updated_at      TIMESTAMPTZ DEFAULT now()
            )
        """)
        # Pool de bots pre-creados (plan B / fallback manual — ver MANAGED_BOTS.md)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_pool (
                id          SERIAL PRIMARY KEY,
                bot_id      BIGINT,
                username    TEXT,
                token       TEXT,
                assigned    BOOLEAN DEFAULT FALSE,
                assigned_at TIMESTAMPTZ
            )
        """)


async def pool() -> asyncpg.Pool:
    if _pool is None:
        await init()
    return _pool


# ─── Customers ────────────────────────────────────────────────────
async def upsert_customer(stripe_customer: str, email: str = "", telegram_id: int | None = None) -> int:
    async with (await pool()).acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO customers (stripe_customer, email, telegram_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (stripe_customer) DO UPDATE
              SET email = COALESCE(NULLIF($2,''), customers.email),
                  telegram_id = COALESCE($3, customers.telegram_id)
            RETURNING id
        """, stripe_customer, email, telegram_id)
        return row["id"]


async def get_customer_by_stripe(stripe_customer: str):
    async with (await pool()).acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM customers WHERE stripe_customer = $1", stripe_customer)


# ─── Subscriptions ────────────────────────────────────────────────
async def upsert_subscription(customer_id: int, stripe_sub: str, status: str,
                              current_period_end: datetime | None = None):
    async with (await pool()).acquire() as conn:
        await conn.execute("""
            INSERT INTO subscriptions (customer_id, stripe_sub, status, current_period_end, updated_at)
            VALUES ($1, $2, $3, $4, now())
            ON CONFLICT (stripe_sub) DO UPDATE
              SET status = $3, current_period_end = $4, updated_at = now()
        """, customer_id, stripe_sub, status, current_period_end)


async def increment_failed_payment(stripe_sub: str) -> int:
    async with (await pool()).acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE subscriptions SET failed_payments = failed_payments + 1, updated_at = now()
            WHERE stripe_sub = $1 RETURNING failed_payments
        """, stripe_sub)
        return row["failed_payments"] if row else 0


async def reset_failed_payments(stripe_sub: str):
    async with (await pool()).acquire() as conn:
        await conn.execute(
            "UPDATE subscriptions SET failed_payments = 0, updated_at = now() WHERE stripe_sub = $1",
            stripe_sub)


# ─── Bot instances ────────────────────────────────────────────────
async def create_bot_instance(customer_id: int, status: str = "provisioning") -> int:
    async with (await pool()).acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO bot_instances (customer_id, status) VALUES ($1, $2) RETURNING id
        """, customer_id, status)
        return row["id"]


async def update_bot_instance(instance_id: int, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(fields))
    async with (await pool()).acquire() as conn:
        await conn.execute(
            f"UPDATE bot_instances SET {cols}, updated_at = now() WHERE id = $1",
            instance_id, *fields.values())


async def get_bot_by_customer(customer_id: int):
    async with (await pool()).acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM bot_instances WHERE customer_id = $1 ORDER BY id DESC LIMIT 1",
            customer_id)


async def get_bot_by_id(instance_id: int):
    async with (await pool()).acquire() as conn:
        return await conn.fetchrow("SELECT * FROM bot_instances WHERE id = $1", instance_id)


async def list_bots():
    """Lista todos los bots desplegados con el id de Telegram de su dueño."""
    async with (await pool()).acquire() as conn:
        return await conn.fetch("""
            SELECT b.id, b.bot_username, b.status, b.railway_project,
                   b.railway_service, b.railway_env, c.telegram_id, c.id AS customer_id
            FROM bot_instances b
            JOIN customers c ON c.id = b.customer_id
            WHERE b.status != 'deleted'
            ORDER BY b.id DESC
        """)
