"""
Orquestación: une todas las piezas.

provision_bot()  → cuando un cliente paga: crea el bot, lo despliega y se lo entrega.
pause_bot()      → cuando deja de pagar: pausa el bot.
resume_bot()     → cuando vuelve a pagar: lo reactiva.

Base de datos de cada bot: usamos UN Postgres compartido y creamos una base de
datos separada por cliente (bot_<id>). Así no hace falta levantar un Postgres por
cada bot. La conexión va por la URL pública del Postgres (CLIENT_DB_URL).
"""
import secrets
from urllib.parse import urlparse, urlunparse

import asyncpg

from . import config, db, railway, telegram_factory


async def crear_base_datos_cliente(customer_id: int) -> str:
    """
    Crea una base de datos dedicada para el bot del cliente dentro del Postgres
    compartido y devuelve la DATABASE_URL que usará ese bot.
    """
    base_url = config.CLIENT_DB_URL
    if not base_url:
        raise RuntimeError("Falta CLIENT_DB_URL (URL pública del Postgres compartido)")

    dbname = f"bot_{customer_id}"
    parsed = urlparse(base_url)

    # Conectar a la base 'postgres' (admin) para poder crear la nueva base
    admin_url = urlunparse(parsed._replace(path="/postgres"))
    conn = await asyncpg.connect(admin_url)
    try:
        existe = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", dbname)
        if not existe:
            await conn.execute(f'CREATE DATABASE "{dbname}"')
    finally:
        await conn.close()

    # URL final que usará el bot del cliente
    return urlunparse(parsed._replace(path=f"/{dbname}"))


async def provision_bot(customer_id: int, bot_token: str, bot_username: str) -> dict:
    """
    Despliega un bot nuevo para un cliente que ya ha pagado.

    Recibe el token del bot (ya creado vía Managed Bots o del pool) y:
      1. Crea proyecto en Railway
      2. Despliega la plantilla del bot desde GitHub
      3. Inyecta las variables (token, etc.)
      4. Marca el bot como activo

    Devuelve los datos del bot desplegado.
    """
    instance_id = await db.create_bot_instance(customer_id, status="provisioning")

    try:
        # 1. Proyecto en Railway
        project_name = f"bot-{bot_username or customer_id}-{secrets.token_hex(3)}"
        project_id = await railway.create_project(project_name)
        env_id = await railway.get_environment(project_id)

        # 2. Servicio desde el repo plantilla
        service_id = await railway.create_service_from_repo(
            project_id, config.BOT_TEMPLATE_REPO, project_name)

        # 2b. Base de datos dedicada para este bot (en el Postgres compartido)
        bot_database_url = await crear_base_datos_cliente(customer_id)

        # 3. Variables de entorno del bot del cliente.
        #    Al crear el servicio desde el repo, Railway ya inicia un build; al meter
        #    estas variables, Railway vuelve a desplegar solo con la config correcta.
        await railway.set_variables(project_id, env_id, service_id, {
            "TOKEN": bot_token,
            "DATABASE_URL": bot_database_url,
            # El cliente configurará el grupo metiendo el bot como admin (auto-detección).
            # GROUP_ID y ADMIN_ID se rellenan en el primer uso o se piden al cliente.
            "GROUP_ID": "0",
            "ADMIN_ID": "0",
            "DEVELOPER_ID": str(config.OWNER_TELEGRAM_ID),
            # Para que el propio bot pueda autogestionar su GROUP_ID en Railway:
            "RAILWAY_TOKEN": config.RAILWAY_TOKEN,
            "RAILWAY_PROJECT_ID": project_id,
            "RAILWAY_SERVICE_ID": service_id,
            "RAILWAY_ENV_ID": env_id,
        })

        # 4. No hace falta deploy explícito: meter las variables de golpe ya dispara
        #    el único redeploy necesario (con la config completa). Lanzar otro deploy
        #    aquí solo crearía instancias solapadas (conflicto de polling).

        # 5. Guardar en BD
        await db.update_bot_instance(
            instance_id,
            bot_username=bot_username,
            bot_token=bot_token,
            railway_project=project_id,
            railway_service=service_id,
            railway_env=env_id,
            status="active",
        )

        return {
            "instance_id": instance_id,
            "project_id": project_id,
            "service_id": service_id,
            "env_id": env_id,
            "bot_username": bot_username,
            "status": "active",
        }

    except Exception as e:
        await db.update_bot_instance(instance_id, status="error")
        raise RuntimeError(f"Fallo al provisionar el bot: {e}") from e


async def pause_bot(customer_id: int) -> bool:
    """Pausa el bot de un cliente (impago / cancelación)."""
    bot = await db.get_bot_by_customer(customer_id)
    if not bot or not bot["railway_service"]:
        return False
    await railway.pause(bot["railway_service"], bot["railway_env"])
    await db.update_bot_instance(bot["id"], status="paused")
    return True


async def resume_bot(customer_id: int) -> bool:
    """Reactiva el bot de un cliente (vuelve a pagar)."""
    bot = await db.get_bot_by_customer(customer_id)
    if not bot or not bot["railway_service"]:
        return False
    await railway.resume(bot["railway_service"], bot["railway_env"])
    await db.update_bot_instance(bot["id"], status="active")
    return True


async def restart_bot(instance_id: int) -> bool:
    """Reinicia (redeploy) el bot de un cliente por su id de instancia."""
    bot = await db.get_bot_by_id(instance_id)
    if not bot or not bot["railway_service"]:
        return False
    await railway.deploy(bot["railway_service"], bot["railway_env"])
    return True


async def delete_bot(instance_id: int) -> bool:
    """
    Borra por completo el bot de un cliente:
    elimina su proyecto de Railway, su base de datos, y lo marca como eliminado.
    """
    bot = await db.get_bot_by_id(instance_id)
    if not bot:
        return False
    # 1. Borrar proyecto de Railway
    if bot["railway_project"]:
        try:
            await railway.delete_project(bot["railway_project"])
        except Exception as e:
            print(f"Aviso al borrar proyecto Railway: {e}")
    # 2. Borrar su base de datos del Postgres compartido
    try:
        base_url = config.CLIENT_DB_URL
        if base_url:
            dbname = f"bot_{bot['customer_id']}"
            parsed = urlparse(base_url)
            admin_url = urlunparse(parsed._replace(path="/postgres"))
            conn = await asyncpg.connect(admin_url)
            try:
                # Cerrar conexiones y borrar la base
                await conn.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=$1", dbname)
                await conn.execute(f'DROP DATABASE IF EXISTS "{dbname}"')
            finally:
                await conn.close()
    except Exception as e:
        print(f"Aviso al borrar base de datos: {e}")
    # 3. Marcar como eliminado
    await db.update_bot_instance(instance_id, status="deleted")
    return True


async def entregar_al_cliente(telegram_id: int, bot_username: str):
    """Le manda al cliente las instrucciones para usar su bot nuevo."""
    if not telegram_id:
        return
    mensaje = (
        "✅ *¡Tu bot ya está listo!*\n\n"
        f"Tu bot es: @{bot_username}\n\n"
        "*Cómo ponerlo en marcha:*\n"
        "1️⃣ Abre tu grupo VIP de Telegram\n"
        "2️⃣ Añádelo como administrador\n"
        "3️⃣ Dale permisos para gestionar usuarios y mensajes\n\n"
        "En cuanto lo metas, el bot detecta tu grupo solo y empieza a funcionar. "
        "Cualquier duda escríbeme. 🤖"
    )
    import aiohttp
    api = f"https://api.telegram.org/bot{config.MASTER_BOT_TOKEN}/sendMessage"
    async with aiohttp.ClientSession() as session:
        await session.post(api, json={
            "chat_id": telegram_id,
            "text": mensaje,
            "parse_mode": "Markdown",
        })
