# 🚀 ROADMAP — Plataforma SaaS de Bots de Telegram

> **Objetivo:** Que cualquier persona pueda pagar (25€ inicial + 5€/mes) y se le cree,
> despliegue y entregue un bot de Telegram para su canal VIP, **totalmente automático**.

---

## 💡 Resumen del negocio

| Concepto | Valor |
|----------|-------|
| Pago inicial | **25€** (puesta en marcha) |
| Suscripción mensual | **5€/mes** |
| Si deja de pagar | El bot se pausa automáticamente |
| Producto | Bot de Telegram para canales VIP (el mismo que ya tenemos) |

---

## 🧩 Las 5 piezas del sistema

```
   CLIENTE
      │  paga 25€ + 5€/mes
      ▼
┌─────────────────┐
│   1. STRIPE     │  pasarela de pago + suscripción recurrente
└────────┬────────┘
         │ webhook "ha pagado"
         ▼
┌─────────────────┐
│ 2. ORQUESTADOR  │  el cerebro (FastAPI). Recibe pagos y coordina todo
└────────┬────────┘
         ├──────────────► 3. TELEGRAM (Managed Bots): crea el bot del cliente
         ├──────────────► 4. RAILWAY (API): despliega el bot
         └──────────────► 5. BASE DE DATOS: guarda quién tiene qué y si paga
```

---

## 📅 FASES (orden de construcción)

### ✅ FASE 0 — Estructura y documentación
- [x] Estructura de carpetas
- [x] Roadmap (este archivo)
- [x] Documentación de arquitectura

### ✅ FASE 1 — Base de datos
- [x] Esquema: clientes, suscripciones, bots desplegados
- [x] Capa de acceso a datos (`db.py`)

### ✅ FASE 2 — Plantilla del bot
- [x] Generalizar el bot de Telegram para cualquier cliente
- [x] Variables parametrizables (token, grupo, admin...)

### ✅ FASE 3 — Automatización de Railway
- [x] Crear proyecto vía API
- [x] Inyectar variables
- [x] Desplegar desde el repo de la plantilla
- [x] Pausar / reanudar servicio

### ✅ FASE 4 — Creación automática del bot (Managed Bots)
- [x] Módulo de creación de bots vía Telegram Bot API 9.6
- [x] Fallback manual documentado (por si la API nueva da problemas)

### ✅ FASE 5 — Stripe
- [x] Productos y precios (25€ + 5€/mes)
- [x] Checkout (link de pago)
- [x] Webhooks (pago OK, pago fallido, cancelación)

### ✅ FASE 6 — Orquestador (unir todo)
- [x] FastAPI con endpoints de webhook
- [x] Flujo completo: pago → crear bot → desplegar → entregar
- [x] Flujo de impago → pausar bot

### 🟡 FASE 7 — Puesta en producción (requiere TU acción)
- [ ] Crear cuenta de Stripe y verificar datos fiscales
- [ ] Activar "Bot Management Mode" en BotFather para el bot maestro
- [ ] Desplegar el orquestador en Railway
- [ ] Configurar las variables de entorno reales
- [ ] Prueba end-to-end con un pago real

---

## 🔑 Lo que necesitarás TÚ (no se puede automatizar)

1. **Cuenta de Stripe verificada** — necesita tus datos fiscales (autónomo/empresa) para cobrar de verdad. Stripe retiene el dinero hasta verificar identidad.
2. **Bot maestro con permiso de gestión** — hay que activar "Bot Management Mode" en @BotFather una vez.
3. **Las claves (API keys)** de Stripe y el token de Railway en las variables de entorno.

Todo lo demás lo hace el sistema solo.

---

## 📁 Estructura de archivos

```
SaaSBots/
├── ROADMAP.md              ← este archivo
├── README.md               ← cómo arrancar todo
├── requirements.txt
├── .env.example            ← plantilla de variables (copiar a .env)
├── orchestrator/           ← el cerebro
│   ├── main.py             ← FastAPI: recibe webhooks de Stripe
│   ├── config.py           ← configuración desde variables de entorno
│   ├── db.py               ← base de datos (clientes, bots, pagos)
│   ├── stripe_handler.py   ← lógica de Stripe
│   ├── railway.py          ← despliegue automático en Railway
│   ├── telegram_factory.py ← creación de bots (Managed Bots)
│   └── provisioning.py     ← orquesta: crear + desplegar + entregar
├── bot_template/           ← el bot que se clona para cada cliente
│   ├── bot.py
│   └── requirements.txt
└── docs/                   ← documentación detallada
    ├── ARCHITECTURE.md
    ├── STRIPE_SETUP.md
    ├── MANAGED_BOTS.md
    └── DEPLOYMENT.md
```

---

## ⏱️ Estado actual

**Construido:** Todo el código del sistema (Fases 0-6).
**Pendiente (requiere tu acción):** Fase 7 — dar de alta cuentas reales y desplegar.

Lee `README.md` para saber cómo arrancar, y `docs/DEPLOYMENT.md` para la puesta en producción.
