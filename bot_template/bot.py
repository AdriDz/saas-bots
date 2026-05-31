"""
PLANTILLA DE BOT — Canal VIP de Telegram (con menú de botones).

Bot autoconfigurable que se despliega para cada cliente. Cuando el cliente lo añade
como admin a su grupo, detecta solo el grupo y el admin. Todo se maneja con botones,
menos difundir un mensaje (para eso se le escribe el mensaje directamente).

Variables de entorno:
  TOKEN, DATABASE_URL, GROUP_ID, ADMIN_ID, DEVELOPER_ID,
  RAILWAY_TOKEN, RAILWAY_PROJECT_ID, RAILWAY_SERVICE_ID, RAILWAY_ENV_ID
"""
import asyncio
import asyncpg
import aiohttp
import random
import sys
import os
from datetime import date, timedelta, datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ApplicationBuilder, CommandHandler, CallbackQueryHandler,
                          MessageHandler, ChatMemberHandler, filters, ContextTypes)

# ========================
# CONFIGURACIÓN
# ========================
TOKEN        = os.environ.get("TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
GROUP_ID     = int(os.environ.get("GROUP_ID", "0"))
ADMIN_ID     = int(os.environ.get("ADMIN_ID", "0"))
DEVELOPER_ID = int(os.environ.get("DEVELOPER_ID", "0"))

RAILWAY_TOKEN      = os.environ.get("RAILWAY_TOKEN", "")
RAILWAY_GQL        = "https://backboard.railway.app/graphql/v2"
RAILWAY_PROJECT_ID = os.environ.get("RAILWAY_PROJECT_ID", "")
RAILWAY_SERVICE_ID = os.environ.get("RAILWAY_SERVICE_ID", "")
RAILWAY_ENV_ID     = os.environ.get("RAILWAY_ENV_ID", "")

ADMINS = [ADMIN_ID] if ADMIN_ID else []
BOT_USERNAME = ""   # se rellena al arrancar
db_pool = None


# ========================
# BASE DE DATOS
# ========================
async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT, full_name TEXT, expiry DATE
            )""")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)""")
        await conn.execute("""
            INSERT INTO config (key, value) VALUES ('broadcast_counter', '0')
            ON CONFLICT (key) DO NOTHING""")


async def cfg_get(key):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT value FROM config WHERE key = $1", key)
        return row["value"] if row else None


async def cfg_set(key, value):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO config (key, value) VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value = $2""", key, str(value))


async def next_broadcast_id():
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE config SET value=(value::int+1)::text WHERE key='broadcast_counter' RETURNING value")
        return int(row["value"])


async def get_users():
    async with db_pool.acquire() as conn:
        return await conn.fetch(
            "SELECT user_id, username, full_name FROM users WHERE expiry IS NULL OR expiry >= $1",
            date.today())


async def get_all_users():
    async with db_pool.acquire() as conn:
        return await conn.fetch("SELECT user_id, username, full_name, expiry FROM users")


async def is_user_active(user_id):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT expiry FROM users WHERE user_id = $1", user_id)
        if not row:
            return False
        return row["expiry"] is None or row["expiry"] >= date.today()


async def register_user(user, expiry):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, username, full_name, expiry) VALUES ($1,$2,$3,$4)
            ON CONFLICT (user_id) DO UPDATE SET username=$2, full_name=$3, expiry=$4""",
            user.id, user.username or "", user.full_name or "", expiry)


def format_user(row):
    return f"{row['full_name'] or 'Sin nombre'} (@{row['username'] or 'sin @'})"


def is_admin(update: Update):
    u = update.effective_user
    return u and u.id in ADMINS


async def notify_admins(bot, message, reply_markup=None):
    for admin_id in ADMINS:
        try:
            await bot.send_message(chat_id=admin_id, text=message,
                                   parse_mode="Markdown", reply_markup=reply_markup)
        except Exception:
            pass


# ========================
# RAILWAY: auto-guardar variables
# ========================
async def railway_set_var(name: str, value: str) -> bool:
    if not (RAILWAY_TOKEN and RAILWAY_PROJECT_ID and RAILWAY_SERVICE_ID and RAILWAY_ENV_ID):
        return False
    mutation = "mutation variableUpsert($input: VariableUpsertInput!) { variableUpsert(input: $input) }"
    payload = {"query": mutation, "variables": {"input": {
        "projectId": RAILWAY_PROJECT_ID, "environmentId": RAILWAY_ENV_ID,
        "serviceId": RAILWAY_SERVICE_ID, "name": name, "value": str(value)}}}
    headers = {"Authorization": f"Bearer {RAILWAY_TOKEN}", "Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(RAILWAY_GQL, json=payload, headers=headers, timeout=30) as r:
                return "errors" not in await r.json()
    except Exception:
        return False


async def railway_reiniciar_self() -> bool:
    """Reinicia (redeploy) este mismo bot en Railway."""
    if not (RAILWAY_TOKEN and RAILWAY_SERVICE_ID and RAILWAY_ENV_ID):
        return False
    mutation = ("mutation serviceInstanceRedeploy($serviceId: String!, $environmentId: String!) "
                "{ serviceInstanceRedeploy(serviceId: $serviceId, environmentId: $environmentId) }")
    payload = {"query": mutation, "variables": {
        "serviceId": RAILWAY_SERVICE_ID, "environmentId": RAILWAY_ENV_ID}}
    headers = {"Authorization": f"Bearer {RAILWAY_TOKEN}", "Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(RAILWAY_GQL, json=payload, headers=headers, timeout=30) as r:
                return "errors" not in await r.json()
    except Exception:
        return False


# ========================
# MENÚ DE BOTONES
# ========================
def menu_principal():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Mis usuarios", callback_data="usuarios")],
        [InlineKeyboardButton("📢 Anuncio de registro", callback_data="anuncio")],
        [InlineKeyboardButton("📣 Difundir un mensaje", callback_data="difundir")],
        [InlineKeyboardButton("➕ Extender acceso", callback_data="extender"),
         InlineKeyboardButton("🚪 Quitar acceso",  callback_data="expulsar")],
        [InlineKeyboardButton("🗑️ Vaciar usuarios", callback_data="vaciar")],
        [InlineKeyboardButton("🔄 Reiniciar bot",   callback_data="reiniciar")],
        [InlineKeyboardButton("❓ Cómo funciona",   callback_data="ayuda")],
    ])


def boton_volver():
    return InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menú", callback_data="menu")]])


TEXTO_MENU = (
    "🤖 *Panel de control*\n\n"
    "Elige una opción 👇\n"
    "_Todo se maneja con los botones. Para difundir un mensaje, pulsa «Difundir» "
    "y escríbeme lo que quieras enviar._"
)


# ========================
# AUTOCONFIGURACIÓN al añadir el bot como admin
# ========================
async def mi_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global GROUP_ID, ADMIN_ID, ADMINS
    result = update.my_chat_member
    if not result:
        return
    old = result.old_chat_member.status
    new = result.new_chat_member.status
    chat = result.chat
    quien = result.from_user

    if old in ("left", "kicked") and new in ("member", "administrator"):
        GROUP_ID = chat.id
        await cfg_set("group_id", chat.id)
        await railway_set_var("GROUP_ID", chat.id)

        if ADMIN_ID == 0 and quien:
            ADMIN_ID = quien.id
            ADMINS = [ADMIN_ID]
            await cfg_set("admin_id", quien.id)
            await railway_set_var("ADMIN_ID", quien.id)

        if ADMIN_ID:
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(f"✅ *¡Bot configurado!*\n\n📛 Grupo: *{chat.title}*\n\n"
                          f"Ya está todo listo. Aquí tienes tu panel 👇"),
                    parse_mode="Markdown", reply_markup=menu_principal())
            except Exception:
                pass

        if DEVELOPER_ID:
            try:
                await context.bot.send_message(
                    chat_id=DEVELOPER_ID,
                    text=(f"🟢 *Bot activado por cliente*\n📛 {chat.title}\n"
                          f"🆔 `{chat.id}`\n👤 Admin: `{ADMIN_ID}`"),
                    parse_mode="Markdown")
            except Exception:
                pass

    elif old in ("member", "administrator") and new in ("left", "kicked"):
        if DEVELOPER_ID:
            try:
                await context.bot.send_message(
                    chat_id=DEVELOPER_ID,
                    text=f"⚠️ *Bot eliminado de un grupo*\n📛 {chat.title}",
                    parse_mode="Markdown")
            except Exception:
                pass


# ========================
# AVISO 3 DÍAS ANTES DE EXPIRAR
# ========================
async def daily_expiry_check(bot):
    while True:
        now = datetime.now()
        next_run = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        await asyncio.sleep((next_run - now).total_seconds())
        target = date.today() + timedelta(days=3)
        async with db_pool.acquire() as conn:
            users = await conn.fetch("SELECT user_id, expiry FROM users WHERE expiry = $1", target)
        for u in users:
            try:
                await bot.send_message(
                    chat_id=u["user_id"],
                    text=(f"⚠️ *Tu acceso expira en 3 días*\n\n"
                          f"📅 Fecha: *{u['expiry'].strftime('%d/%m/%Y')}*\n\n"
                          f"Contacta con el admin para renovar."),
                    parse_mode="Markdown")
            except Exception:
                pass


# ========================
# NUEVOS MIEMBROS
# ========================
async def nuevo_miembro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member
    if not result or result.chat.id != GROUP_ID:
        return
    old = result.old_chat_member.status
    new = result.new_chat_member.status
    user = result.new_chat_member.user
    if user.is_bot:
        return

    if old in ("left", "kicked") and new == "member":
        expiry = date.today() + timedelta(days=31)
        await register_user(user, expiry)
        try:
            await context.bot.send_message(
                chat_id=user.id,
                text=(f"✅ *¡Bienvenido al VIP!*\n\n"
                      f"📅 Acceso válido hasta el *{expiry.strftime('%d/%m/%Y')}*\n\n"
                      f"Recibirás los avisos aquí directamente. 🔔"),
                parse_mode="Markdown")
        except Exception:
            pass
        await notify_admins(context.bot,
            f"🆕 *Nuevo miembro*\n👤 {user.full_name} (@{user.username or 'sin @'})\n"
            f"🆔 `{user.id}`\n📅 Hasta: *{expiry.strftime('%d/%m/%Y')}*")

    elif old == "member" and new in ("left", "kicked"):
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE users SET expiry=$1 WHERE user_id=$2",
                               date.today() - timedelta(days=1), user.id)
        await notify_admins(context.bot,
            f"🚪 *Miembro salido*\n👤 {user.full_name} (@{user.username or 'sin @'})\n🆔 `{user.id}`")


# ========================
# BROADCAST
# ========================
async def broadcast_logic(bot, msg, broadcast_id):
    users = list(await get_users())
    random.shuffle(users)
    total = len(users)
    enviados = fallidos = 0
    tanda_size, espera = 5, 180

    await notify_admins(bot,
        f"🚀 *Difusión #{broadcast_id} iniciada* ({total} activos)\n📦 Tandas de 5 cada 3 min")

    for i in range(0, total, tanda_size):
        tanda = users[i:i + tanda_size]
        ok, fail = [], []
        for row in tanda:
            try:
                uid = row["user_id"]
                if msg.photo:
                    await bot.send_photo(uid, msg.photo[-1].file_id, caption=msg.caption, protect_content=True)
                elif msg.video:
                    await bot.send_video(uid, msg.video.file_id, caption=msg.caption, protect_content=True)
                elif msg.document:
                    await bot.send_document(uid, msg.document.file_id, caption=msg.caption, protect_content=True)
                elif msg.audio:
                    await bot.send_audio(uid, msg.audio.file_id, caption=msg.caption, protect_content=True)
                elif msg.voice:
                    await bot.send_voice(uid, msg.voice.file_id, caption=msg.caption, protect_content=True)
                elif msg.sticker:
                    await bot.send_sticker(uid, msg.sticker.file_id, protect_content=True)
                elif msg.animation:
                    await bot.send_animation(uid, msg.animation.file_id, caption=msg.caption, protect_content=True)
                elif msg.text:
                    await bot.send_message(uid, msg.text, protect_content=True)
                enviados += 1
                ok.append(f"✅ {format_user(row)}")
            except Exception:
                fallidos += 1
                fail.append(f"❌ {format_user(row)}")
            await asyncio.sleep(0.3)

        for admin_id in ADMINS:
            try:
                await bot.send_message(admin_id,
                    f"📦 #{broadcast_id} — Tanda {i // tanda_size + 1}\n\n" +
                    "\n".join(ok + fail) + f"\n\n📊 {enviados + fallidos}/{total}")
            except Exception:
                pass
        if i + tanda_size < total:
            await asyncio.sleep(espera)

    await notify_admins(bot,
        f"🏁 *Difusión #{broadcast_id} finalizada*\n✅ {enviados} | ❌ {fallidos} | 👥 {total}")


# ========================
# /start  (admin → menú ; usuario → registro)
# ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # Admin → panel de botones
    if user.id in ADMINS:
        await update.message.reply_text(TEXTO_MENU, parse_mode="Markdown",
                                        reply_markup=menu_principal())
        return

    # Usuario normal → intentar registrarlo si está en el grupo
    if await is_user_active(user.id):
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT expiry FROM users WHERE user_id=$1", user.id)
        exp = row["expiry"].strftime('%d/%m/%Y') if row and row["expiry"] else "este mes"
        await update.message.reply_text(
            f"✅ *Ya tienes acceso activo.*\n\n📅 Expira el *{exp}*", parse_mode="Markdown")
        return

    en_grupo = False
    if GROUP_ID:
        try:
            member = await context.bot.get_chat_member(GROUP_ID, user.id)
            en_grupo = member.status in ("member", "administrator", "creator")
        except Exception:
            en_grupo = False

    if en_grupo:
        expiry = date.today() + timedelta(days=31)
        await register_user(user, expiry)
        await update.message.reply_text(
            f"✅ *¡Registrado correctamente!*\n\n📅 Acceso hasta el *{expiry.strftime('%d/%m/%Y')}*\n\n"
            f"A partir de ahora recibirás los avisos aquí. 🔔", parse_mode="Markdown")
    else:
        await update.message.reply_text(
            "🔐 *Acceso restringido.*\n\nNecesitas ser miembro del canal VIP para registrarte.",
            parse_mode="Markdown")


# ========================
# BOTONES (callbacks)
# ========================
async def boton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in ADMINS:
        return
    data = query.data

    if data == "menu":
        context.user_data.pop("esperando", None)
        await query.edit_message_text(TEXTO_MENU, parse_mode="Markdown", reply_markup=menu_principal())

    elif data == "usuarios":
        users = await get_all_users()
        activos = sum(1 for r in users if not r["expiry"] or r["expiry"] >= date.today())
        cab = (f"👥 *Tus usuarios*\n\n"
               f"Total: *{len(users)}*  ·  ✅ Activos: *{activos}*  ·  ❌ Caducados: *{len(users)-activos}*\n\n")
        if not users:
            await query.edit_message_text(cab + "_Aún no hay usuarios registrados._",
                                          parse_mode="Markdown", reply_markup=boton_volver())
            return
        lineas = []
        for r in users[:50]:
            estado = "✅" if not r["expiry"] or r["expiry"] >= date.today() else "❌"
            exp = r["expiry"].strftime('%d/%m/%Y') if r["expiry"] else "sin fecha"
            lineas.append(f"{estado} {format_user(r)} — {exp}")
        extra = f"\n\n_…y {len(users)-50} más_" if len(users) > 50 else ""
        await query.edit_message_text(cab + "\n".join(lineas) + extra,
                                      parse_mode="Markdown", reply_markup=boton_volver())

    elif data == "anuncio":
        if not GROUP_ID:
            await query.edit_message_text(
                "⚠️ Primero añádeme a tu grupo como administrador.",
                reply_markup=boton_volver())
            return
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(
            "📲 Registrarme en el bot", url=f"https://t.me/{BOT_USERNAME}?start=registro")]])
        try:
            await context.bot.send_message(
                chat_id=GROUP_ID,
                text=("📣 *¿Quieres recibir los avisos directamente en tu privado?*\n\n"
                      "Pulsa el botón y quedarás registrado en el bot. 🔔"),
                parse_mode="Markdown", reply_markup=kb)
            await query.edit_message_text("✅ Anuncio enviado a tu grupo.", reply_markup=boton_volver())
        except Exception as e:
            await query.edit_message_text(f"❌ No pude enviarlo: {e}", reply_markup=boton_volver())

    elif data == "difundir":
        context.user_data["esperando"] = "broadcast"
        await query.edit_message_text(
            "📣 *Difundir un mensaje*\n\nEscríbeme ahora el mensaje que quieres enviar a todos "
            "tus usuarios. Puede ser texto, foto, vídeo, audio... Lo mando yo en tandas.\n\n"
            "_(o pulsa Menú para cancelar)_",
            parse_mode="Markdown", reply_markup=boton_volver())

    elif data == "extender":
        context.user_data["esperando"] = "extender"
        await query.edit_message_text(
            "➕ *Extender acceso*\n\nMándame el ID del usuario y los días, separados por un espacio.\n"
            "Ejemplo: `123456789 30`\n\n_(o pulsa Menú para cancelar)_",
            parse_mode="Markdown", reply_markup=boton_volver())

    elif data == "expulsar":
        context.user_data["esperando"] = "expulsar"
        await query.edit_message_text(
            "🚪 *Quitar acceso*\n\nMándame el ID del usuario al que quieres quitar el acceso.\n"
            "Ejemplo: `123456789`\n\n_(o pulsa Menú para cancelar)_",
            parse_mode="Markdown", reply_markup=boton_volver())

    elif data == "vaciar":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚠️ Sí, vaciar todo", callback_data="vaciar_ok")],
            [InlineKeyboardButton("↩️ Cancelar", callback_data="menu")]])
        await query.edit_message_text(
            "🗑️ *¿Seguro que quieres borrar TODOS los usuarios?*\n\nEsto no se puede deshacer.",
            parse_mode="Markdown", reply_markup=kb)

    elif data == "vaciar_ok":
        users = await get_all_users()
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM users")
        await query.edit_message_text(
            f"🗑️ Hecho. Eliminados *{len(users)}* usuarios.", parse_mode="Markdown",
            reply_markup=boton_volver())

    elif data == "reiniciar":
        await query.edit_message_text("🔄 Reiniciando tu bot... estará listo en ~30 segundos.")
        ok = await railway_reiniciar_self()
        msg = ("✅ Bot reiniciado. En unos segundos vuelve a estar activo."
               if ok else "❌ No pude reiniciar el bot. Avisa al soporte.")
        await query.edit_message_text(msg, reply_markup=boton_volver())

    elif data == "ayuda":
        await query.edit_message_text(AYUDA, parse_mode="Markdown", reply_markup=boton_volver())


AYUDA = (
    "❓ *Cómo funciona tu bot*\n\n"
    "Tu bot gestiona tu canal VIP solo. Esto es lo que hace:\n\n"
    "👥 *Mis usuarios*\n"
    "Ve cuánta gente tienes, quién está activo y quién caducó.\n\n"
    "📢 *Anuncio de registro*\n"
    "Manda a tu grupo un mensaje con un botón para que la gente se registre en el bot "
    "y reciba los avisos en su privado.\n\n"
    "📣 *Difundir un mensaje*\n"
    "Pulsa el botón y escríbeme lo que quieras (texto, foto, vídeo...). Lo envío a todos "
    "tus usuarios en tandas para que Telegram no te bloquee.\n\n"
    "➕ *Extender acceso* / 🚪 *Quitar acceso*\n"
    "Amplía o retira el acceso de un usuario por su ID.\n\n"
    "🗑️ *Vaciar usuarios*\n"
    "Borra todos los usuarios (para empezar de cero).\n\n"
    "_Automático:_ cuando alguien entra a tu grupo se registra solo, y 3 días antes de "
    "caducar se le avisa. Tú no tienes que hacer nada. 🤖"
)


# ========================
# TEXTO (según lo que se esté esperando)
# ========================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    esperando = context.user_data.get("esperando")

    if esperando == "broadcast":
        context.user_data.pop("esperando", None)
        bid = await next_broadcast_id()
        asyncio.create_task(broadcast_logic(context.bot, update.message, bid))
        await update.message.reply_text(
            f"🚀 *Difusión #{bid} en marcha.* Te voy informando.",
            parse_mode="Markdown", reply_markup=boton_volver())
        return

    if esperando == "extender":
        context.user_data.pop("esperando", None)
        partes = (update.message.text or "").split()
        if len(partes) < 2 or not partes[0].isdigit() or not partes[1].lstrip('-').isdigit():
            await update.message.reply_text("❌ Formato: `ID DIAS` (ej: `123456789 30`)",
                                            parse_mode="Markdown", reply_markup=boton_volver())
            return
        user_id, dias = int(partes[0]), int(partes[1])
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT expiry, full_name FROM users WHERE user_id=$1", user_id)
            if not row:
                await update.message.reply_text("❌ Usuario no encontrado.", reply_markup=boton_volver())
                return
            base = max(row["expiry"], date.today()) if row["expiry"] else date.today()
            nueva = base + timedelta(days=dias)
            await conn.execute("UPDATE users SET expiry=$1 WHERE user_id=$2", nueva, user_id)
        await update.message.reply_text(
            f"✅ Acceso extendido.\n📅 Nueva fecha: *{nueva.strftime('%d/%m/%Y')}*",
            parse_mode="Markdown", reply_markup=boton_volver())
        try:
            await context.bot.send_message(user_id,
                f"✅ *Tu acceso ha sido renovado.*\n📅 Hasta: *{nueva.strftime('%d/%m/%Y')}*",
                parse_mode="Markdown")
        except Exception:
            pass
        return

    if esperando == "expulsar":
        context.user_data.pop("esperando", None)
        txt = (update.message.text or "").strip()
        if not txt.isdigit():
            await update.message.reply_text("❌ Mándame solo el ID (números).",
                                            reply_markup=boton_volver())
            return
        user_id = int(txt)
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT full_name FROM users WHERE user_id=$1", user_id)
            if not row:
                await update.message.reply_text("❌ Usuario no encontrado.", reply_markup=boton_volver())
                return
            await conn.execute("UPDATE users SET expiry=$1 WHERE user_id=$2",
                               date.today() - timedelta(days=1), user_id)
        await update.message.reply_text("✅ Acceso retirado.", reply_markup=boton_volver())
        try:
            await context.bot.send_message(user_id,
                "❌ *Tu acceso al bot ha sido desactivado.*", parse_mode="Markdown")
        except Exception:
            pass
        return

    # Sin nada esperando → mostrar el menú
    await update.message.reply_text(TEXTO_MENU, parse_mode="Markdown", reply_markup=menu_principal())


# ========================
# ARRANQUE
# ========================
async def on_startup(app):
    global GROUP_ID, ADMIN_ID, ADMINS, BOT_USERNAME
    await init_db()
    g = await cfg_get("group_id")
    if g:
        GROUP_ID = int(g)
    a = await cfg_get("admin_id")
    if a:
        ADMIN_ID = int(a)
        ADMINS = [ADMIN_ID]
    me = await app.bot.get_me()
    BOT_USERNAME = me.username
    asyncio.create_task(daily_expiry_check(app.bot))
    if DEVELOPER_ID:
        try:
            await app.bot.send_message(DEVELOPER_ID, "🟢 Bot iniciado.")
        except Exception:
            pass


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    app = ApplicationBuilder().token(TOKEN).post_init(on_startup).build()
    app.add_handler(ChatMemberHandler(nuevo_miembro, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(mi_estado, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", start))
    app.add_handler(CallbackQueryHandler(boton))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.ALL & ~filters.COMMAND, handle_text))
    print("🤖 Bot plantilla corriendo...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
