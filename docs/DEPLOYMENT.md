# 🚀 Puesta en producción (Fase 7)

Esto es lo que tienes que hacer TÚ para arrancar el sistema en real.
Todo el código ya está hecho; aquí solo se conectan las cuentas.

---

## Checklist

- [ ] 1. Subir la plantilla del bot a un repo de GitHub
- [ ] 2. Crear el bot maestro en BotFather
- [ ] 3. Crear cuenta de Stripe + productos + webhook
- [ ] 4. Desplegar el orquestador en Railway
- [ ] 5. Poner las variables de entorno
- [ ] 6. (Opción A) Montar el pool de bots / (Opción B) activar Managed Bots
- [ ] 7. Prueba end-to-end

---

## 1. Subir la plantilla del bot a GitHub

El orquestador despliega el bot clonando un repo. Crea uno solo con la plantilla:

```bash
cd SaaSBots/bot_template
git init
gh repo create bot-template --private --source=. --push
```

Apunta el nombre (`tu-usuario/bot-template`) → variable `BOT_TEMPLATE_REPO`.

---

## 2. Crear el bot maestro

1. Habla con @BotFather → `/newbot` → ponle nombre (p. ej. "VIP Bots Manager")
2. Copia el token → variable `MASTER_BOT_TOKEN`
3. (Para Managed Bots) Activa "Bot Management Mode" — ver `MANAGED_BOTS.md`

---

## 3. Stripe

Sigue `STRIPE_SETUP.md` entero. Sacarás:
`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_SETUP`, `STRIPE_PRICE_MONTHLY`.

> El webhook apunta a `https://TU-ORQUESTADOR.up.railway.app/webhook/stripe`,
> así que primero despliega el orquestador (paso 4) para saber la URL, y luego
> configura el webhook en Stripe.

---

## 4. Desplegar el orquestador en Railway

1. Sube esta carpeta (`SaaSBots/`) a un repo de GitHub:
   ```bash
   cd SaaSBots
   git init && git add -A && git commit -m "orquestador SaaS bots"
   gh repo create saas-bots --private --source=. --push
   ```
2. En Railway → New Project → Deploy from GitHub → elige `saas-bots`
3. Añade un **Postgres** al proyecto (botón + → Database → PostgreSQL).
   Railway crea la variable `DATABASE_URL` sola.
4. Railway detecta el `Procfile` y arranca el orquestador.
5. En Settings → Networking → genera un dominio público → esa es tu `PUBLIC_URL`.

---

## 5. Variables de entorno en Railway

En el servicio del orquestador → Variables, añade todas las de `.env.example`:

```
DATABASE_URL=          (la pone Railway sola)
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
STRIPE_PRICE_SETUP=
STRIPE_PRICE_MONTHLY=
MASTER_BOT_TOKEN=
OWNER_TELEGRAM_ID=
RAILWAY_TOKEN=
BOT_TEMPLATE_REPO=
PUBLIC_URL=
```

---

## 6. Bots: pool o Managed Bots

**Opción A (recomendada para empezar) — Pool:** sigue la sección "pool" de
`MANAGED_BOTS.md`. Creas 10-20 bots a mano y los metes en la tabla `bot_pool`.

**Opción B — Managed Bots:** activa el permiso en BotFather y configura el webhook
del bot maestro a `https://TU-ORQUESTADOR.up.railway.app/webhook/telegram`:
```bash
curl "https://api.telegram.org/bot<MASTER_BOT_TOKEN>/setWebhook?url=https://TU-ORQUESTADOR.up.railway.app/webhook/telegram"
```

---

## 7. Prueba end-to-end

1. En modo test de Stripe, crea un Checkout:
   ```bash
   curl -X POST https://TU-ORQUESTADOR.up.railway.app/comprar \
     -H "Content-Type: application/json" \
     -d '{"telegram_id": TU_ID}'
   ```
   Te devuelve una URL de pago.
2. Abre la URL, paga con la tarjeta de prueba `4242 4242 4242 4242`.
3. Comprueba en los logs del orquestador que:
   - Llega el webhook `checkout.session.completed`
   - Se asigna/crea un bot
   - Se despliega en Railway
   - Te llega el mensaje con el bot a tu Telegram
4. Añade el bot a un grupo de prueba como admin → debe autoconfigurarse.

---

## Mantenimiento

- **Ver clientes:** consulta la tabla `customers` en Railway → Postgres → Database.
- **Rellenar el pool:** inserta más bots en `bot_pool` cuando se vacíe.
- **Un bot da problemas:** Railway → proyecto del cliente → Logs.
