# 🏗️ Arquitectura del sistema

## Flujo completo (cliente paga → bot funcionando)

```
1. Cliente entra a tu landing/canal y pulsa "Quiero mi bot"
       │
       ▼
2. Se le abre un Checkout de Stripe (25€ ahora + suscripción de 5€/mes)
       │
       ▼
3. Cliente paga ──────► Stripe le cobra y crea la suscripción
       │
       ▼
4. Stripe manda un webhook a nuestro ORQUESTADOR:
   evento "checkout.session.completed"
       │
       ▼
5. El ORQUESTADOR:
   a) Guarda el cliente en la base de datos
   b) Crea el bot del cliente en Telegram (Managed Bots)
   c) Obtiene el token del bot nuevo
   d) Crea un proyecto en Railway y despliega el bot con ese token
   e) Marca el bot como "activo" en la base de datos
       │
       ▼
6. El ORQUESTADOR le manda al cliente (por Telegram o email):
   - El @usuario de su bot nuevo
   - Instrucciones de cómo meterlo en su grupo como admin
       │
       ▼
7. Cliente añade el bot a su grupo → el bot empieza a funcionar solo
```

## Flujo de cobro mensual

```
Cada mes, Stripe intenta cobrar 5€ automáticamente.

  ✅ Pago OK    → webhook "invoice.paid"            → no se hace nada (sigue activo)
  ❌ Pago falla → webhook "invoice.payment_failed"  → tras N reintentos, se pausa el bot
  🚫 Cancela    → webhook "customer.subscription.deleted" → se pausa el bot
```

## Componentes

### Orquestador (FastAPI)
El cerebro. Es un servidor web que:
- Expone endpoints HTTPS para que Stripe le mande los webhooks
- Coordina la creación y despliegue de bots
- Gestiona el ciclo de vida (activar/pausar) según los pagos

Vive en Railway, siempre encendido.

### Base de datos (Postgres)
Tres tablas principales:
- `customers` — clientes (su id de Telegram, email, id de Stripe)
- `subscriptions` — estado de pago de cada cliente
- `bot_instances` — bots desplegados (token, proyecto Railway, estado)

### Telegram Factory (Managed Bots)
Usa la API nueva de Telegram (Bot API 9.6, abril 2026) para crear bots hijos
sin pasar por BotFather a mano. Ver `MANAGED_BOTS.md`.

### Railway Deployer
Reutiliza la API GraphQL de Railway que ya usamos. Crea proyecto, mete variables,
despliega desde el repo plantilla, y puede pausar/reanudar.

### Bot Template
El bot de canal VIP que ya tenemos, generalizado para que funcione con cualquier
cliente solo cambiando las variables de entorno.

## Seguridad

- Los webhooks de Stripe se verifican con firma (`STRIPE_WEBHOOK_SECRET`) para que
  nadie pueda falsificar un "ha pagado".
- Los tokens de los bots de clientes se guardan cifrados en la base de datos.
- El token de Railway y las claves de Stripe nunca van en el código, solo en
  variables de entorno.

## Por qué FastAPI

- Asíncrono (maneja muchos webhooks a la vez sin bloquear)
- Verificación de firmas de Stripe sencilla
- Se despliega en Railway igual que los bots
