"""
PLANTILLA DE BOT — Canal VIP de Telegram.

Este es el bot que se despliega para cada cliente. Es el mismo bot de canal VIP
que ya tenemos, pero AUTOCONFIGURABLE: cuando el cliente lo añade como administrador
a su grupo, el bot detecta solo:
  - El grupo (GROUP_ID)
  - El admin (la persona que lo añadió → ADMIN_ID)
y los guarda en la base de datos y en las variables de Railway, de forma que el
cliente no tiene que tocar nada técnico.

Variables de entorno necesarias:
  TOKEN          → token del bot (lo pone el orquestador)
  DATABASE_URL   → base de datos (la pone Railway)
  RAILWAY_TOKEN  → para auto-guardar GROUP_ID/ADMIN_ID (lo pone el orquestador)
  GROUP_ID       → 0 al principio; se auto-rellena
  ADMIN_ID       → 0 al principio; se auto-rellena
  DEVELOPER_ID   → tu id (recibe avisos)
  RAILWAY_PROJECT_ID / RAILWAY_SERVICE_ID / RAILWAY_ENV_ID → para la auto-config
"""
import asyncio
import asyncpg
import aiohttp
import random
import sys
import os
import secrets
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
            CREATE TABLE IF NOT EXISTS codes (
                code TEXT PRIMARY KEY, used BOOLEAN DEFAULT FALSE,
                used_by BIGINT, expiry DATE
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


async def create_code(conn, days=31):
    code = secrets.token_hex(4).upper()
    expiry = date.today() + timedelta(days=days)
    await conn.execute("INSERT INTO codes (code, used, expiry) VALUES ($1, FALSE, $2)", code, expiry)
    return code, expiry


async def use_code(conn, code, user_id):
    row = await conn.fetchrow("SELECT * FROM codes WHERE code = $1", code)
    if not row:
        return None, "❌ Código inválido."
    if row["used"]:
        return None, "❌ Código ya usado."
    if row["expiry"] < date.today():
        return None, "❌ Código caducado."
    await conn.execute("UPDATE codes SET used=TRUE, used_by=$1 WHERE code=$2", user_id, code)
    return row["expiry"], None


def format_user(row):
    return f"{row['full_name'] or 'Sin nombre'} (@{row['username'] or 'sin @'})"


def is_admin(update: Update):
    return update.effective_user and update.effective_user.id in ADMINS


async def notify_admins(bot, message):
    for admin_id in ADMINS:
        try:
            await bot.send_message(chat_id=admin_id, text=message, parse_mode="Markdown")
        except Exception:
            pass


# ========================
# RAILWAY: auto-guardar variables
# ========================
async def railway_set_var(name: str, value: str) -> bool:
    if not (RAILWAY_TOKEN and RAILWAY_PROJECT_ID and RAILWAY_SERVICE_ID and RAILWAY_ENV_ID):
        return False
    mutation = """
    mutation variableUpsert($input: VariableUpsertInput!) { variableUpsert(input: $input) }
    """
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


# ========================
# AUTOCONFIGURACIÓN al añadir el bot como admin
# ========================
async def mi_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cuando añaden o quitan el bot de un grupo."""
    global GROUP_ID, ADMIN_ID, ADMINS
    result = update.my_chat_member
    if not result:
        return
    old = result.old_chat_member.status
    new = result.new_chat_member.status
    chat = result.chat
    quien = result.from_user

    # Bot añadido como admin a un grupo → autoconfigurar
    if old in ("left", "kicked") and new in ("member", "administrator"):
        primera_vez = (GROUP_ID == 0)

        GROUP_ID = chat.id
        await cfg_set("group_id", chat.id)
        await railway_set_var("GROUP_ID", chat.id)

        # La persona que lo añade se convierte en el admin (si aún no hay)
        if ADMIN_ID == 0 and quien:
            ADMIN_ID = quien.id
            ADMINS = [ADMIN_ID]
            await cfg_set("admin_id", quien.id)
            await railway_set_var("ADMIN_ID", quien.id)

        # Avisar al cliente (admin) por privado
        if ADMIN_ID:
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(f"✅ *¡Bot configurado!*\n\n"
                          f"📛 Grupo: *{chat.title}*\n\n"
                          f"Ya está todo listo. Escríbeme aquí en privado /ayuda "
                          f"para ver todo lo que puedes hacer."),
                    parse_mode="Markdown")
            except Exception:
                pass

        # Avisar al desarrollador (nosotros)
        if DEVELOPER_ID:
            try:
                await context.bot.send_message(
                    chat_id=DEVELOPER_ID,
                    text=(f"🟢 *Bot activado por cliente*\n\n"
                          f"📛 {chat.title}\n🆔 `{chat.id}`\n"
                          f"👤 Admin: `{ADMIN_ID}`"),
                    parse_mode="Markdown")
            except Exception:
                pass

    elif old in ("member", "administrator") and new in ("left", "kicked"):
        if DEVELOPER_ID:
            try:
                await context.bot.send_message(
                    chat_id=DEVELOPER_ID,
                    text=f"⚠️ *Bot eliminado de un grupo*\n\n📛 {chat.title}\n🆔 `{chat.id}`",
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
                      f"📅 Tu acceso es válido hasta el *{expiry.strftime('%d/%m/%Y')}*\n\n"
                      f"Recibirás los avisos aquí directamente. 🔔"),
                parse_mode="Markdown")
        except Exception:
            pass
        await notify_admins(context.bot,
            f"🆕 *Nuevo miembro*\n\n👤 {user.full_name} (@{user.username or 'sin @'})\n"
            f"🆔 `{user.id}`\n📅 Hasta: *{expiry.strftime('%d/%m/%Y')}*")

    elif old == "member" and new in ("left", "kicked"):
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE users SET expiry=$1 WHERE user_id=$2",
                               date.today() - timedelta(days=1), user.id)
        await notify_admins(context.bot,
            f"🚪 *Miembro salido*\n\n👤 {user.full_name} (@{user.username or 'sin @'})\n🆔 `{user.id}`")


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
        f"🚀 *Broadcast #{broadcast_id} iniciado* ({total} activos)\n📦 Tandas de 5 cada 3 min")

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
        f"🏁 *Broadcast #{broadcast_id} finalizado*\n✅ {enviados} | ❌ {fallidos} | 👥 {total}")


async def encolar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    bid = await next_broadcast_id()
    asyncio.create_task(broadcast_logic(context.bot, update.message, bid))
    await update.message.reply_text(f"🚀 *Broadcast #{bid} lanzado*", parse_mode="Markdown")


# ========================
# COMANDOS
# ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if await is_user_active(user.id):
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT expiry FROM users WHERE user_id=$1", user.id)
        exp = row["expiry"].strftime('%d/%m/%Y') if row and row["expiry"] else "este mes"
        await update.message.reply_text(
            f"✅ *Ya tienes acceso activo.*\n\n📅 Expira el *{exp}*", parse_mode="Markdown")
        return
    if GROUP_ID:
        try:
            member = await context.bot.get_chat_member(GROUP_ID, user.id)
            en_grupo = member.status in ("member", "administrator", "creator")
        except Exception:
            en_grupo = False
    else:
        en_grupo = False
    if en_grupo:
        expiry = date.today() + timedelta(days=31)
        await register_user(user, expiry)
        await update.message.reply_text(
            f"✅ *¡Registrado!*\n\n📅 Acceso hasta el *{expiry.strftime('%d/%m/%Y')}*",
            parse_mode="Markdown")
    else:
        await update.message.reply_text(
            "🔐 *Acceso restringido.*\n\nNecesitas ser miembro del canal VIP.",
            parse_mode="Markdown")


async def activar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args:
        await update.message.reply_text("Uso: `/activar CODIGO`", parse_mode="Markdown")
        return
    code = context.args[0].upper()
    async with db_pool.acquire() as conn:
        expiry, error = await use_code(conn, code, user.id)
    if error:
        await update.message.reply_text(error)
        return
    await register_user(user, expiry)
    await update.message.reply_text(
        f"✅ *Código activado.*\n\n📅 Acceso hasta el *{expiry.strftime('%d/%m/%Y')}*",
        parse_mode="Markdown")


async def generar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    cantidad = int(context.args[0]) if context.args else 1
    dias = int(context.args[1]) if len(context.args) > 1 else 31
    async with db_pool.acquire() as conn:
        codigos = []
        for _ in range(cantidad):
            code, expiry = await create_code(conn, days=dias)
            codigos.append(f"`{code}` — hasta {expiry.strftime('%d/%m/%Y')}")
    await update.message.reply_text(
        f"🎟️ *{cantidad} código(s) de {dias} días:*\n\n" + "\n".join(codigos), parse_mode="Markdown")


async def codigos_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT code, used, used_by, expiry FROM codes ORDER BY expiry DESC")
    if not rows:
        await update.message.reply_text("No hay códigos.")
        return
    lines = [f"`{r['code']}` — {'✅ usado' if r['used'] else '🟡 libre'} — {r['expiry'].strftime('%d/%m/%Y')}"
             for r in rows]
    await update.message.reply_text(("🎟️ *Códigos:*\n\n" + "\n".join(lines))[:4000], parse_mode="Markdown")


async def extender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Uso: `/extender USER_ID DIAS`", parse_mode="Markdown")
        return
    try:
        user_id, dias = int(context.args[0]), int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Deben ser números.")
        return
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT expiry, full_name FROM users WHERE user_id=$1", user_id)
        if not row:
            await update.message.reply_text("❌ Usuario no encontrado.")
            return
        base = max(row["expiry"], date.today()) if row["expiry"] else date.today()
        new_expiry = base + timedelta(days=dias)
        await conn.execute("UPDATE users SET expiry=$1 WHERE user_id=$2", new_expiry, user_id)
    await update.message.reply_text(
        f"✅ *Extendido*\n📅 Nueva expiración: *{new_expiry.strftime('%d/%m/%Y')}*", parse_mode="Markdown")
    try:
        await context.bot.send_message(user_id,
            f"✅ *Acceso renovado.*\n📅 Hasta: *{new_expiry.strftime('%d/%m/%Y')}*", parse_mode="Markdown")
    except Exception:
        pass


async def expulsar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: `/expulsar USER_ID`", parse_mode="Markdown")
        return
    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Debe ser un número.")
        return
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT full_name FROM users WHERE user_id=$1", user_id)
        if not row:
            await update.message.reply_text("❌ Usuario no encontrado.")
            return
        await conn.execute("UPDATE users SET expiry=$1 WHERE user_id=$2",
                           date.today() - timedelta(days=1), user_id)
    await update.message.reply_text(f"✅ Usuario expulsado.", parse_mode="Markdown")


async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🆔 `{update.effective_chat.id}`", parse_mode="Markdown")


async def total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    users = await get_all_users()
    activos = sum(1 for r in users if not r["expiry"] or r["expiry"] >= date.today())
    await update.message.reply_text(
        f"👥 Total: *{len(users)}*\n✅ Activos: *{activos}*\n❌ Caducados: *{len(users)-activos}*",
        parse_mode="Markdown")


async def lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    users = await get_all_users()
    if not users:
        await update.message.reply_text("No hay usuarios.")
        return
    chunk = "👥 *Usuarios:*\n\n"
    for r in users:
        estado = "✅" if not r["expiry"] or r["expiry"] >= date.today() else "❌"
        exp = r["expiry"].strftime('%d/%m/%Y') if r["expiry"] else "sin fecha"
        line = f"{estado} {format_user(r)} — {exp}\n"
        if len(chunk) + len(line) > 4000:
            await update.message.reply_text(chunk, parse_mode="Markdown")
            chunk = ""
        chunk += line
    if chunk:
        await update.message.reply_text(chunk, parse_mode="Markdown")


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not context.args or context.args[0] != "CONFIRMAR":
        await update.message.reply_text(
            "⚠️ Escribe `/reset CONFIRMAR` para borrar todos los usuarios.", parse_mode="Markdown")
        return
    users = await get_all_users()
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM users")
    await update.message.reply_text(f"🗑️ Eliminados *{len(users)}* usuarios.", parse_mode="Markdown")


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    await update.message.reply_text(
        "📋 *Comandos:*\n\n"
        "✉️ Escríbeme cualquier mensaje (en privado) → broadcast a todos\n\n"
        "🎟️ /activar CODIGO · /generar N D · /codigos\n"
        "/extender ID DIAS · /expulsar ID\n"
        "📊 /total · /lista · /reset CONFIRMAR\n"
        "🔧 /id · /ayuda",
        parse_mode="Markdown")


async def on_startup(app):
    global GROUP_ID, ADMIN_ID, ADMINS
    await init_db()
    g = await cfg_get("group_id")
    if g:
        GROUP_ID = int(g)
    a = await cfg_get("admin_id")
    if a:
        ADMIN_ID = int(a)
        ADMINS = [ADMIN_ID]
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
    app.add_handler(CommandHandler("activar", activar))
    app.add_handler(CommandHandler("id", get_id))
    app.add_handler(CommandHandler("total", total))
    app.add_handler(CommandHandler("lista", lista))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(CommandHandler("generar", generar))
    app.add_handler(CommandHandler("codigos", codigos_cmd))
    app.add_handler(CommandHandler("extender", extender))
    app.add_handler(CommandHandler("expulsar", expulsar))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.ALL & ~filters.COMMAND, encolar))
    print("🤖 Bot plantilla corriendo...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
