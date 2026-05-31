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

## Infraestructura ya montada (modo prueba)

**Repos GitHub:**
- Orquestador: `AdriDz/saas-bots`
- Plantilla bot: `AdriDz/bot-template`

**Railway — proyecto `saas-bots-orquestador`:**
- Project ID: `189a3363-47cb-4e3f-afe1-9c974aef934f`
- Environment ID: `bfcdfd55-e41d-46d0-919f-db2e329d7a3f`
- Servicio orquestador ID: `b5bc4e71-639e-421e-951c-f47b157111eb`
- URL pública: `https://orquestador-production-120a.up.railway.app`

**Variables ya puestas en el orquestador:**
- [x] `STRIPE_PRICE_SETUP`
- [x] `STRIPE_PRICE_MONTHLY`
- [x] `MASTER_BOT_TOKEN`
- [x] `RAILWAY_TOKEN`
- [x] `BOT_TEMPLATE_REPO`
- [x] `MAX_PAYMENT_RETRIES`
- [x] `PUBLIC_URL`

---

## Pendiente (lo poco que falta para probar)

- [ ] **Postgres** → añadirlo en el panel de Railway (1 clic) para tener `DATABASE_URL`
- [ ] `STRIPE_SECRET_KEY` → clave secreta de prueba (`sk_test_...`) de Stripe
- [ ] `STRIPE_WEBHOOK_SECRET` → al crear el webhook en Stripe
- [ ] `OWNER_TELEGRAM_ID` → tu id de Telegram
- [ ] Crear el webhook de Stripe apuntando a la URL pública
- [ ] Meter 1 bot en el pool para la prueba

---

## Siguiente paso

Añadir Postgres en el panel de Railway y meter las 2 claves de Stripe.
Ver el mensaje del chat para los pasos exactos.
