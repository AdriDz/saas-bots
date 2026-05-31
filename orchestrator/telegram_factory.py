"""
Creación automática de bots de Telegram usando "Managed Bots"
(Telegram Bot API 9.6, abril 2026).

Un BOT MAESTRO con el permiso `can_manage_bots` activado puede crear bots hijos
en nombre del usuario, sin que el usuario tenga que hablar con @BotFather.

Flujo:
  1. El cliente abre el bot maestro y pulsa un botón (KeyboardButtonRequestManagedBot).
  2. Telegram le muestra una pantalla pre-rellenada para crear el bot.
  3. El cliente confirma con dos toques.
  4. Llega un mensaje `ManagedBotCreated` con el id del bot nuevo.
  5. Llamamos a `getManagedBotToken` para obtener el token y usarlo en el deploy.

Como la API es muy nueva y las librerías aún no la soportan del todo, aquí se llama
directamente a la API HTTP de Telegram. Si algo falla, ver el FALLBACK MANUAL abajo
y en docs/MANAGED_BOTS.md.
"""
import aiohttp

from . import config

API_BASE = f"https://api.telegram.org/bot{config.MASTER_BOT_TOKEN}"


async def _call(method: str, params: dict | None = None) -> dict:
    """Llama a un método de la Bot API del bot maestro."""
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_BASE}/{method}", json=params or {}, timeout=30) as resp:
            data = await resp.json()
            if not data.get("ok"):
                raise RuntimeError(f"Telegram API error en {method}: {data}")
            return data["result"]


async def check_can_manage_bots() -> bool:
    """Comprueba que el bot maestro tiene el permiso de gestión activado."""
    me = await _call("getMe")
    return bool(me.get("can_manage_bots"))


async def send_create_bot_button(chat_id: int, nombre_sugerido: str = "Bot VIP"):
    """
    Manda al cliente un botón para crear su bot.
    Al pulsarlo, Telegram abre la pantalla de creación pre-rellenada.
    """
    keyboard = {
        "keyboard": [[{
            "text": "🤖 Crear mi bot",
            "request_managed_bot": {
                "request_id": 1,
                "name": nombre_sugerido,
            },
        }]],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }
    await _call("sendMessage", {
        "chat_id": chat_id,
        "text": (
            "¡Pago recibido! 🎉\n\n"
            "Pulsa el botón de abajo para crear tu bot. "
            "Telegram te pedirá confirmar con dos toques y listo."
        ),
        "reply_markup": keyboard,
    })


async def get_managed_bot_token(bot_id: int) -> str:
    """
    Obtiene el token de un bot gestionado ya creado.
    Se llama cuando recibimos el evento ManagedBotCreated.
    """
    result = await _call("getManagedBotToken", {"bot_id": bot_id})
    # La API devuelve el token como string
    return result if isinstance(result, str) else result.get("token", "")


async def revoke_managed_bot_token(bot_id: int) -> str:
    """Revoca y regenera el token de un bot gestionado (por seguridad)."""
    result = await _call("replaceManagedBotToken", {"bot_id": bot_id})
    return result if isinstance(result, str) else result.get("token", "")


def extraer_bot_creado(update: dict) -> dict | None:
    """
    Dado un update de Telegram, extrae la info del bot recién creado
    si contiene un evento ManagedBotCreated.

    Devuelve {"bot_id": int, "username": str} o None.
    """
    # El bot creado puede llegar como mensaje de servicio o como update managed_bot
    msg = update.get("message", {})
    created = msg.get("managed_bot_created") or update.get("managed_bot")
    if not created:
        return None
    bot = created.get("bot", created)
    return {
        "bot_id": bot.get("id") or bot.get("bot_id"),
        "username": bot.get("username", ""),
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
