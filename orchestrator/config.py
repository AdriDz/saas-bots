"""
Configuración central del orquestador.
Todo se lee de variables de entorno — nunca hardcodear claves aquí.
"""
import os


# ─── Base de datos ────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ─── Stripe ───────────────────────────────────────────────────────
STRIPE_SECRET_KEY      = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET  = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
# Precios creados en el panel de Stripe (ver docs/STRIPE_SETUP.md)
STRIPE_PRICE_SETUP     = os.environ.get("STRIPE_PRICE_SETUP", "")    # 25€ pago único
STRIPE_PRICE_MONTHLY   = os.environ.get("STRIPE_PRICE_MONTHLY", "")  # 5€/mes
# Reintentos de cobro fallido antes de pausar el bot
MAX_PAYMENT_RETRIES    = int(os.environ.get("MAX_PAYMENT_RETRIES", "3"))

# ─── Telegram ─────────────────────────────────────────────────────
# Token del BOT MAESTRO (el que crea los bots de los clientes)
MASTER_BOT_TOKEN       = os.environ.get("MASTER_BOT_TOKEN", "")
# Tu id de Telegram (para recibir avisos de admin)
OWNER_TELEGRAM_ID      = int(os.environ.get("OWNER_TELEGRAM_ID", "0"))

# ─── Railway ──────────────────────────────────────────────────────
RAILWAY_TOKEN          = os.environ.get("RAILWAY_TOKEN", "")
RAILWAY_GQL            = "https://backboard.railway.app/graphql/v2"
# Repo de GitHub con la plantilla del bot (lo clona Railway en cada deploy)
BOT_TEMPLATE_REPO      = os.environ.get("BOT_TEMPLATE_REPO", "")     # ej: AdriDz/bot-template

# ─── App ──────────────────────────────────────────────────────────
PUBLIC_URL             = os.environ.get("PUBLIC_URL", "")  # URL pública del orquestador
PORT                   = int(os.environ.get("PORT", "8000"))


def validar() -> list[str]:
    """Devuelve una lista de variables obligatorias que faltan."""
    obligatorias = {
        "DATABASE_URL": DATABASE_URL,
        "STRIPE_SECRET_KEY": STRIPE_SECRET_KEY,
        "STRIPE_WEBHOOK_SECRET": STRIPE_WEBHOOK_SECRET,
        "MASTER_BOT_TOKEN": MASTER_BOT_TOKEN,
        "RAILWAY_TOKEN": RAILWAY_TOKEN,
    }
    return [nombre for nombre, valor in obligatorias.items() if not valor]
