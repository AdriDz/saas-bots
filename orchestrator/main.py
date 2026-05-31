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

        # Crear el bot: intenta Managed Bots; si no, del pool
        bot = None
        try:
            bot = await telegram_factory.asignar_del_pool()
        except Exception as e:
            log.warning("Pool no disponible: %s", e)

        if bot:
            try:
                resultado = await provisioning.provision_bot(
                    customer_id, bot["token"], bot["username"])
                if datos["telegram_id"]:
                    await provisioning.entregar_al_cliente(
                        datos["telegram_id"], resultado["bot_username"])
            except Exception as e:
                log.exception("Error provisionando bot")
        else:
            # Sin pool: avisar al cliente para crear el bot vía Managed Bots
            if datos["telegram_id"]:
                try:
                    await telegram_factory.send_create_bot_button(datos["telegram_id"])
                except Exception as e:
                    log.warning("No se pudo mandar botón de creación: %s", e)

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


# ─── Webhook del bot maestro (Managed Bots) ───────────────────────
@app.post("/webhook/telegram")
async def webhook_telegram(request: Request):
    """
    Recibe updates del bot maestro. Cuando un cliente crea su bot vía Managed Bots,
    aquí llega el evento, obtenemos el token y desplegamos.
    """
    update = await request.json()
    creado = telegram_factory.extraer_bot_creado(update)
    if not creado:
        return {"ok": True}

    log.info("🤖 Bot creado vía Managed Bots: %s", creado)
    try:
        token = await telegram_factory.get_managed_bot_token(creado["bot_id"])
        # Buscar al cliente por su telegram_id (quien creó el bot)
        from_id = (update.get("message", {}).get("from", {}) or {}).get("id")
        cust = None
        if from_id:
            async with (await db.pool()).acquire() as conn:
                cust = await conn.fetchrow(
                    "SELECT * FROM customers WHERE telegram_id = $1", from_id)
        if cust:
            resultado = await provisioning.provision_bot(
                cust["id"], token, creado["username"])
            await provisioning.entregar_al_cliente(from_id, resultado["bot_username"])
    except Exception as e:
        log.exception("Error procesando bot creado: %s", e)

    return {"ok": True}


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
