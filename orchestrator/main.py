"""
Orquestador — FastAPI.

Expone:
  GET  /                      → estado del servicio
  POST /comprar               → crea un Checkout de Stripe y devuelve el link de pago
  POST /webhook/stripe        → recibe los eventos de Stripe (pagos, impagos, cancelaciones)
  POST /webhook/telegram      → recibe updates del bot maestro (bots creados)
  GET  /exito                 → página tras pagar
  GET  /cancelado             → página si cancela el pago

Es el único servicio que hay que tener siempre encendido en Railway.
"""
import logging

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from . import config, db, stripe_handler, provisioning, telegram_factory

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("orquestador")

app = FastAPI(title="SaaS Bots — Orquestador")


@app.on_event("startup")
async def startup():
    faltan = config.validar()
    if faltan:
        log.warning("⚠️ Faltan variables de entorno: %s", ", ".join(faltan))
    await db.init()
    log.info("✅ Orquestador arrancado")


@app.get("/")
async def estado():
    faltan = config.validar()
    return {
        "servicio": "SaaS Bots — Orquestador",
        "estado": "ok" if not faltan else "configuracion incompleta",
        "faltan_variables": faltan,
    }


# ─── Panel de administración (lo usa InfoBot) ─────────────────────
def _check_admin_key(request: Request):
    key = request.headers.get("x-admin-key") or request.query_params.get("key", "")
    if not config.ADMIN_KEY or key != config.ADMIN_KEY:
        raise HTTPException(401, "No autorizado")


@app.get("/admin/bots")
async def admin_listar_bots(request: Request):
    """Lista todos los bots vendidos (para el panel de InfoBot)."""
    _check_admin_key(request)
    bots = await db.list_bots()
    return {"bots": [dict(b) for b in bots]}


@app.post("/admin/restart")
async def admin_restart(request: Request):
    """Reinicia el bot de un cliente. Body: {"instance_id": N}."""
    _check_admin_key(request)
    body = await request.json()
    ok = await provisioning.restart_bot(int(body["instance_id"]))
    return {"ok": ok}


@app.post("/admin/delete")
async def admin_delete(request: Request):
    """Borra el bot de un cliente. Body: {"instance_id": N}."""
    _check_admin_key(request)
    body = await request.json()
    ok = await provisioning.delete_bot(int(body["instance_id"]))
    return {"ok": ok}


@app.get("/admin/bot-users")
async def admin_bot_users(request: Request):
    """Resumen de usuarios del bot de un cliente. Parámetro: ?instance_id=N."""
    _check_admin_key(request)
    instance_id = int(request.query_params.get("instance_id", "0"))
    return await provisioning.contar_usuarios_bot(instance_id)


# ─── Crear link de pago ───────────────────────────────────────────
@app.post("/comprar")
async def comprar(request: Request):
    """
    Crea un Checkout de Stripe. Body opcional: {"telegram_id": 123}.
    Devuelve {"url": "https://checkout.stripe.com/..."}.
    """
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    telegram_id = body.get("telegram_id")
    try:
        url = stripe_handler.crear_checkout(telegram_id)
        return {"url": url}
    except Exception as e:
        log.exception("Error creando checkout")
        raise HTTPException(500, f"Error creando checkout: {e}")


# ─── Webhook de Stripe ────────────────────────────────────────────
@app.post("/webhook/stripe")
async def webhook_stripe(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe_handler.verificar_webhook(payload, sig)
    except Exception as e:
        log.warning("Webhook con firma inválida: %s", e)
        raise HTTPException(400, "Firma inválida")

    tipo = event["type"]
    log.info("📨 Evento Stripe: %s", tipo)

    # ── Pago inicial completado → crear y desplegar el bot ──
    if tipo == "checkout.session.completed":
        datos = stripe_handler.datos_checkout_completado(event)
        customer_id = await db.upsert_customer(
            datos["stripe_customer"], datos["email"], datos["telegram_id"])
        await db.upsert_subscription(customer_id, datos["stripe_sub"], "active")

        # VÍA PRINCIPAL — Managed Bots: mandamos al cliente el enlace de creación.
        # El cliente elige el nombre, crea el bot, y el deploy se hace al recibir
        # el evento en /webhook/telegram.
        if datos["telegram_id"]:
            try:
                await telegram_factory.send_create_bot_link(datos["telegram_id"])
                log.info("✉️ Enlace de creación enviado al cliente %s", customer_id)
            except Exception as e:
                log.warning("No se pudo mandar el enlace de creación: %s", e)
                # FALLBACK — pool de bots pre-creados
                try:
                    bot = await telegram_factory.asignar_del_pool()
                    if bot:
                        resultado = await provisioning.provision_bot(
                            customer_id, bot["token"], bot["username"])
                        await provisioning.entregar_al_cliente(
                            datos["telegram_id"], resultado["bot_username"])
                except Exception:
                    log.exception("Fallback de pool también falló")
        else:
            log.warning("Pago sin telegram_id: no se puede entregar el bot al cliente")

    # ── Pago mensual OK → resetear contador de fallos ──
    elif tipo == "invoice.paid":
        datos = stripe_handler.datos_factura(event)
        if datos["stripe_sub"]:
            await db.reset_failed_payments(datos["stripe_sub"])

    # ── Pago mensual fallido → contar; si supera el límite, pausar ──
    elif tipo == "invoice.payment_failed":
        datos = stripe_handler.datos_factura(event)
        if datos["stripe_sub"]:
            fallos = await db.increment_failed_payment(datos["stripe_sub"])
            log.info("Pago fallido #%s para %s", fallos, datos["stripe_sub"])
            if fallos >= config.MAX_PAYMENT_RETRIES:
                cust = await db.get_customer_by_stripe(datos["stripe_customer"])
                if cust:
                    await provisioning.pause_bot(cust["id"])
                    log.info("⏸️ Bot pausado por impago: cliente %s", cust["id"])

    # ── Suscripción cancelada → pausar el bot ──
    elif tipo == "customer.subscription.deleted":
        datos = stripe_handler.datos_suscripcion(event)
        cust = await db.get_customer_by_stripe(datos["stripe_customer"])
        if cust:
            await db.upsert_subscription(cust["id"], datos["stripe_sub"], "canceled")
            await provisioning.pause_bot(cust["id"])
            log.info("🚫 Bot pausado por cancelación: cliente %s", cust["id"])

    return JSONResponse({"recibido": True})


# ─── Webhook del bot maestro (menú + Managed Bots) ────────────────
@app.post("/webhook/telegram")
async def webhook_telegram(request: Request):
    """
    Recibe TODOS los updates del bot maestro:
      - /start                → mensaje de bienvenida con botón de compra
      - botón "comprar"        → genera el pago de Stripe y manda el link
      - bot creado (managed)   → obtiene el token, despliega y entrega
    """
    update = await request.json()

    # 1) ¿Es un bot recién creado vía Managed Bots?
    creado = telegram_factory.extraer_bot_creado(update)
    if creado:
        await _procesar_bot_creado(creado)
        return {"ok": True}

    # 2) ¿Pulsó un botón? (callback_query)
    if "callback_query" in update:
        cq = update["callback_query"]
        chat_id = cq["from"]["id"]
        data = cq.get("data", "")
        try:
            await telegram_factory.answer_callback(cq["id"])
            if data == "comprar":
                url = stripe_handler.crear_checkout(chat_id)
                await telegram_factory.send_payment_link(chat_id, url)
        except Exception as e:
            log.exception("Error en callback: %s", e)
        return {"ok": True}

    # 3) ¿Es un mensaje de texto? (/start u otros)
    msg = update.get("message")
    if msg and "text" in msg:
        chat_id = msg["chat"]["id"]
        texto = msg["text"].strip()
        try:
            if texto.startswith("/start"):
                await telegram_factory.send_welcome(chat_id)
            else:
                # Cualquier otro texto → reenseñar el menú
                await telegram_factory.send_welcome(chat_id)
        except Exception as e:
            log.exception("Error atendiendo mensaje: %s", e)
        return {"ok": True}

    return {"ok": True}


async def _procesar_bot_creado(creado: dict):
    """Despliega y entrega el bot que un cliente acaba de crear."""
    log.info("🤖 Bot creado vía Managed Bots: %s", creado)
    try:
        token = await telegram_factory.get_managed_bot_token(creado["bot_id"])
        owner_id = creado.get("owner_id")
        cust = None
        if owner_id:
            async with (await db.pool()).acquire() as conn:
                cust = await conn.fetchrow(
                    "SELECT * FROM customers WHERE telegram_id = $1", owner_id)
        if cust:
            # Idempotencia: si Telegram reenvía el evento de creación, no provisionar
            # un segundo bot para el mismo cliente (evita proyectos duplicados con el
            # mismo token y el consiguiente conflicto de polling).
            existente = await db.get_bot_by_customer(cust["id"])
            if existente and existente["status"] in ("provisioning", "active"):
                log.info("⏭️ Ya hay un bot (%s) para el cliente %s, ignoro evento duplicado",
                         existente["status"], cust["id"])
                return
            await telegram_factory.send_message(
                owner_id, "⏳ Creando y desplegando tu bot... dame unos segundos.")
            resultado = await provisioning.provision_bot(
                cust["id"], token, creado["username"])
            await provisioning.entregar_al_cliente(owner_id, resultado["bot_username"])
            log.info("✅ Bot desplegado y entregado al cliente %s", cust["id"])
        else:
            log.warning("Bot creado pero no encontré al cliente (owner_id=%s)", owner_id)
    except Exception as e:
        log.exception("Error procesando bot creado: %s", e)


# ─── Portal de cliente (cancelar suscripción) ────────────────────
@app.get("/portal")
async def portal_cliente(request: Request):
    """
    Crea una sesión del portal de Stripe para que el cliente gestione su suscripción.
    Parámetro: ?cid=stripe_customer_id
    Redirige al portal de Stripe.
    """
    from fastapi.responses import RedirectResponse
    import stripe
    cid = request.query_params.get("cid", "")
    if not cid:
        raise HTTPException(400, "Falta el parámetro cid")
    # Verificar que el customer existe en nuestra BD
    cust = await db.get_customer_by_stripe(cid)
    if not cust:
        raise HTTPException(404, "Cliente no encontrado")
    try:
        stripe.api_key = config.STRIPE_SECRET_KEY
        session = stripe.billing_portal.Session.create(
            customer=cid,
            return_url="https://t.me/MisVIPBots_bot",
        )
        return RedirectResponse(session.url)
    except Exception as e:
        log.exception("Error creando portal session: %s", e)
        raise HTTPException(500, "Error al abrir el portal")


# ─── Páginas de retorno ───────────────────────────────────────────
@app.get("/exito", response_class=HTMLResponse)
async def exito():
    return """
    <html><body style="font-family:sans-serif;text-align:center;padding:60px">
      <h1>✅ ¡Pago recibido!</h1>
      <p>Tu bot se está creando. En unos minutos lo recibirás por Telegram.</p>
    </body></html>
    """


@app.get("/cancelado", response_class=HTMLResponse)
async def cancelado():
    return """
    <html><body style="font-family:sans-serif;text-align:center;padding:60px">
      <h1>Pago cancelado</h1>
      <p>No se ha cobrado nada. Puedes volver a intentarlo cuando quieras.</p>
    </body></html>
    """


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
