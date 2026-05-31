"""
Creación automática de bots de Telegram usando "Managed Bots"
(Telegram Bot API 9.6, abril 2026).

Un BOT MAESTRO con el permiso `can_manage_bots` activado puede crear bots hijos
en nombre del usuario, sin que el usuario tenga que hablar con @BotFather.

Flujo (con enlace mágico):
  1. El cliente paga → el bot maestro le manda un enlace de creación.
  2. El cliente abre el enlace → Telegram le muestra una pantalla de creación
     pre-rellenada donde PUEDE PONER EL NOMBRE QUE QUIERA.
  3. El cliente confirma → el bot queda creado y gestionado por el bot maestro.
  4. Llega un update con `managed_bot` (ManagedBotUpdated) / mensaje `managed_bot_created`.
  5. Llamamos a `getManagedBotToken` para obtener el token y desplegar.

Formato del enlace (oficial):
  https://t.me/newbot/{master_bot_username}/{username_sugerido}?name={nombre_sugerido}

Se llama directo a la API HTTP de Telegram porque la función es muy nueva.
"""
import secrets
import aiohttp

from . import config

API_BASE = f"https://api.telegram.org/bot{config.MASTER_BOT_TOKEN}"

# Cache del username del bot maestro (se rellena en la primera llamada)
_master_username: str | None = None


async def _call(method: str, params: dict | None = None) -> dict:
    """Llama a un método de la Bot API del bot maestro."""
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_BASE}/{method}", json=params or {}, timeout=30) as resp:
            data = await resp.json()
            if not data.get("ok"):
                raise RuntimeError(f"Telegram API error en {method}: {data}")
            return data["result"]


async def get_master_username() -> str:
    """Devuelve el @username del bot maestro (cacheado)."""
    global _master_username
    if _master_username is None:
        me = await _call("getMe")
        _master_username = me.get("username", "")
    return _master_username


# ─────────────────────────────────────────────────────────────────
# BOT MAESTRO INTERACTIVO (menú, botones, mensajes)
# ─────────────────────────────────────────────────────────────────
async def send_message(chat_id: int, text: str, reply_markup: dict | None = None):
    params = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        params["reply_markup"] = reply_markup
    await _call("sendMessage", params)


async def answer_callback(callback_query_id: str, text: str = ""):
    """Confirma la pulsación de un botón (quita el 'cargando')."""
    await _call("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})


async def send_welcome(chat_id: int):
    """Mensaje de bienvenida con botón de compra."""
    texto = (
        "👋 *¡Hola!*\n\n"
        "Te monto un *bot de Telegram para tu canal VIP* que lo gestiona todo solo:\n\n"
        "— Registra a quien entra y sale de tu grupo\n"
        "— Manda mensajes masivos a todos tus miembros\n"
        "— Avisa cuando alguien está por expirar\n"
        "— Funciona 24/7 sin que toques nada\n\n"
        "💰 *25€* de puesta en marcha + *5€/mes*\n\n"
        "Pulsa el botón para empezar 👇"
    )
    teclado = {"inline_keyboard": [[{"text": "💳 Quiero mi bot", "callback_data": "comprar"}]]}
    await send_message(chat_id, texto, teclado)


async def send_payment_link(chat_id: int, url: str):
    """Manda el botón con el link de pago de Stripe."""
    texto = (
        "Perfecto 🙌\n\n"
        "Pulsa para pagar de forma segura. En cuanto completes el pago, "
        "te mando aquí mismo el enlace para crear tu bot con el nombre que quieras."
    )
    teclado = {"inline_keyboard": [[{"text": "💳 Pagar ahora", "url": url}]]}
    await send_message(chat_id, texto, teclado)


async def check_can_manage_bots() -> bool:
    """Comprueba que el bot maestro tiene el permiso de gestión activado."""
    me = await _call("getMe")
    return bool(me.get("can_manage_bots"))


def _sugerir_username() -> str:
    """Genera un @username sugerido único (el cliente puede cambiarlo). Debe acabar en 'bot'."""
    return f"vip{secrets.token_hex(4)}bot"


async def send_create_bot_link(chat_id: int, nombre_sugerido: str = "Mi Bot VIP"):
    """
    Manda al cliente el enlace para crear su bot.
    Al abrirlo, Telegram muestra la pantalla de creación donde el cliente
    elige el nombre y el @usuario que quiera.
    """
    master = await get_master_username()
    username_sug = _sugerir_username()
    nombre_url = nombre_sugerido.replace(" ", "%20")
    link = f"https://t.me/newbot/{master}/{username_sug}?name={nombre_url}"

    keyboard = {"inline_keyboard": [[{"text": "🤖 Crear mi bot", "url": link}]]}
    await _call("sendMessage", {
        "chat_id": chat_id,
        "text": (
            "¡Pago recibido! 🎉\n\n"
            "Pulsa el botón para crear tu bot. En la pantalla que se abre puedes "
            "ponerle el *nombre que quieras* y confirmar. ¡En unos segundos lo tendrás listo!"
        ),
        "parse_mode": "Markdown",
        "reply_markup": keyboard,
    })


async def get_managed_bot_token(bot_id: int) -> str:
    """
    Obtiene el token de un bot gestionado ya creado.
    Se llama cuando recibimos el evento ManagedBotCreated.
    El parámetro de la API es `user_id` (el id del bot creado).
    """
    result = await _call("getManagedBotToken", {"user_id": bot_id})
    # La API devuelve el token como string
    return result if isinstance(result, str) else result.get("token", "")


async def revoke_managed_bot_token(bot_id: int) -> str:
    """Revoca y regenera el token de un bot gestionado (por seguridad)."""
    result = await _call("replaceManagedBotToken", {"user_id": bot_id})
    return result if isinstance(result, str) else result.get("token", "")


def extraer_bot_creado(update: dict) -> dict | None:
    """
    Dado un update de Telegram, extrae la info del bot recién creado
    si contiene un evento de Managed Bots.

    Devuelve {"bot_id": int, "username": str, "owner_id": int} o None.
      - bot_id/username → del bot recién creado
      - owner_id → el cliente que lo creó (para entregárselo)
    """
    msg = update.get("message", {})
    # managed_bot_created (en un mensaje) o managed_bot (ManagedBotUpdated, en el update)
    created = msg.get("managed_bot_created") or update.get("managed_bot")
    if not created:
        return None

    bot = created.get("bot", created)
    # El dueño: en ManagedBotUpdated viene como "user"; si no, el "from" del mensaje
    owner = created.get("user") or msg.get("from") or {}

    return {
        "bot_id": bot.get("id") or bot.get("bot_id"),
        "username": bot.get("username", ""),
        "owner_id": owner.get("id"),
    }


# ─────────────────────────────────────────────────────────────────
# FALLBACK MANUAL
# ─────────────────────────────────────────────────────────────────
# Si Managed Bots no funciona (API muy nueva, librería sin soporte, etc.),
# se puede operar con un POOL de bots pre-creados a mano:
#
#   1. Creas con @BotFather, p.ej. 20 bots: vip_bot_001 ... vip_bot_020
#   2. Guardas sus tokens en la tabla `bot_pool` (ver MANAGED_BOTS.md)
#   3. Cuando un cliente paga, coges un token libre del pool y lo asignas
#
# Así el sistema sigue siendo automático de cara al cliente, solo que tú
# rellenas el pool de vez en cuando (5 min de trabajo cada X ventas).

async def asignar_del_pool() -> dict | None:
    """
    Coge un bot libre del pool de bots pre-creados (fallback manual).
    Devuelve {"bot_id", "username", "token"} o None si el pool está vacío.
    Requiere la tabla bot_pool (ver MANAGED_BOTS.md).
    """
    from . import db
    async with (await db.pool()).acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE bot_pool SET assigned = TRUE, assigned_at = now()
            WHERE id = (SELECT id FROM bot_pool WHERE assigned = FALSE ORDER BY id LIMIT 1)
            RETURNING bot_id, username, token
        """)
        return dict(row) if row else None
