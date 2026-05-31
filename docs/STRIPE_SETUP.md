# 💳 Configurar Stripe (paso a paso)

Stripe es la pasarela de pago. Te permite cobrar los 25€ iniciales y los 5€/mes
automáticamente. Es lo que en tu idea llamabas "Spinter" 😉.

---

## 1. Crear cuenta

1. Entra en https://stripe.com y crea una cuenta
2. **Importante:** para cobrar dinero de verdad tienes que verificar tu identidad
   (DNI + datos fiscales como autónomo o empresa). Mientras no lo hagas, Stripe
   funciona en **modo prueba** (puedes probar todo con tarjetas falsas, pero no
   cobras dinero real).

---

## 2. Crear los productos y precios

En el panel de Stripe → **Productos** → **Añadir producto**:

### Producto A — Puesta en marcha (pago único)
- Nombre: `Puesta en marcha bot VIP`
- Precio: **25€**
- Tipo: **Pago único** (one-time)
- Copia el `price_id` que te da (empieza por `price_...`) → va en `STRIPE_PRICE_SETUP`

### Producto B — Mantenimiento mensual
- Nombre: `Mantenimiento bot VIP`
- Precio: **5€**
- Tipo: **Recurrente / mensual**
- Copia el `price_id` → va en `STRIPE_PRICE_MONTHLY`

---

## 3. Sacar las API keys

Panel → **Desarrolladores** → **Claves de API**:
- **Clave secreta** (`sk_live_...` o `sk_test_...`) → va en `STRIPE_SECRET_KEY`

---

## 4. Configurar el webhook

El webhook es cómo Stripe avisa a tu orquestador de que alguien ha pagado.

Panel → **Desarrolladores** → **Webhooks** → **Añadir endpoint**:
- URL del endpoint: `https://TU-ORQUESTADOR.up.railway.app/webhook/stripe`
- Eventos a escuchar (selecciona estos 4):
  - `checkout.session.completed`
  - `invoice.paid`
  - `invoice.payment_failed`
  - `customer.subscription.deleted`
- Tras crearlo, copia el **Signing secret** (`whsec_...`) → va en `STRIPE_WEBHOOK_SECRET`

---

## 5. Resumen de variables que sacas de Stripe

```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_SETUP=price_...     (el de 25€)
STRIPE_PRICE_MONTHLY=price_...   (el de 5€/mes)
```

---

## 6. Cómo funciona el cobro

- **Primer pago:** el cliente paga 25€ + 5€ = 30€ (puesta en marcha + primer mes)
- **A partir del mes 2:** Stripe cobra 5€ automáticamente cada mes
- **Si falla un cobro:** Stripe reintenta solo. Tras 3 intentos fallidos
  (`MAX_PAYMENT_RETRIES`), el orquestador pausa el bot.
- **Si el cliente cancela:** el bot se pausa al instante.

---

## 7. Probar sin dinero real (modo test)

Usa las claves `sk_test_...` y la tarjeta de prueba `4242 4242 4242 4242`
(cualquier fecha futura, cualquier CVC). Así pruebas todo el flujo sin cobrar nada.
