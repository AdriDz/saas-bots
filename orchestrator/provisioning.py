"""
Orquestación: une todas las piezas.

provision_bot()  → cuando un cliente paga: crea el bot, lo despliega y se lo entrega.
pause_bot()      → cuando deja de pagar: pausa el bot.
resume_bot()     → cuando vuelve a pagar: lo reactiva.
"""
import secrets

from . import config, db, railway, telegram_factory


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

        # 3. Variables de entorno del bot del cliente
        await railway.set_variables(project_id, env_id, service_id, {
            "TOKEN": bot_token,
            # El cliente configurará el grupo metiendo el bot como admin (auto-detección).
            # GROUP_ID y ADMIN_ID se rellenan en el primer uso o se piden al cliente.
            "GROUP_ID": "0",
            "ADMIN_ID": "0",
            "DEVELOPER_ID": str(config.OWNER_TELEGRAM_ID),
            # Para que el propio bot pueda autogestionar su GROUP_ID en Railway:
            "RAILWAY_TOKEN": config.RAILWAY_TOKEN,
        })

        # 4. Desplegar
        await railway.deploy(service_id, env_id)

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
