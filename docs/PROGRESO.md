# 📝 Progreso de la configuración

Aquí vamos apuntando los datos que se van consiguiendo para el despliegue.

---

## Stripe — MODO PRUEBA (test)

Productos creados en modo prueba:

| Producto | Precio | Price ID (test) |
|----------|--------|-----------------|
| Puesta en marcha bot | 25€ (único) | `price_1TdHGjDa9vsiC9hh0e8ESZ48` |
| Mantenimiento mensual | 5€/mes | `price_1TdHH2Da9vsiC9hhyIeks4ZL` |

➡️ En las variables:
```
STRIPE_PRICE_SETUP=price_1TdHGjDa9vsiC9hh0e8ESZ48
STRIPE_PRICE_MONTHLY=price_1TdHH2Da9vsiC9hhyIeks4ZL
```

> ⚠️ **IMPORTANTE:** estos son los IDs de **modo prueba**. Cuando verifiques la empresa
> y pases a **modo real (live)**, tendrás que crear los productos otra vez en modo live
> y conseguir unos `price_...` NUEVOS (los de prueba no sirven para cobrar dinero real).

---

## Pendiente de conseguir

- [ ] `STRIPE_SECRET_KEY` (la clave secreta — se pone directa en Railway, no en el chat)
- [ ] `STRIPE_WEBHOOK_SECRET` (al configurar el webhook, después de desplegar el orquestador)
- [ ] `MASTER_BOT_TOKEN` (crear bot maestro en BotFather)
- [ ] `OWNER_TELEGRAM_ID` (tu id de Telegram)
- [x] `RAILWAY_TOKEN` (ya lo tenemos: el de siempre)
- [ ] `BOT_TEMPLATE_REPO` (subir la plantilla del bot a GitHub)
- [ ] `PUBLIC_URL` (al desplegar el orquestador en Railway)

---

## Siguiente paso

Crear el **bot maestro** en BotFather y conseguir su token, o subir la plantilla
del bot a GitHub. Ver `DEPLOYMENT.md`.
