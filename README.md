# 🤖 SaaS Bots — Plataforma de bots de Telegram automática

Sistema que permite a cualquiera **pagar y recibir un bot de Telegram para su
canal VIP, totalmente automático**. Pago de 25€ inicial + 5€/mes.

> **¿Por dónde empiezo?** Lee `ROADMAP.md` para la visión general y
> `docs/DEPLOYMENT.md` para ponerlo en marcha.

---

## Qué hace

1. El cliente paga (Stripe): 25€ + 5€/mes
2. El sistema crea su bot de Telegram automáticamente
3. Lo despliega en Railway con su propia base de datos
4. Se lo entrega al cliente con instrucciones
5. Cada mes cobra los 5€ solos; si deja de pagar, pausa el bot

Todo sin que tú toques nada en cada venta.

---

## Estructura

```
SaaSBots/
├── ROADMAP.md              Visión general y fases
├── README.md               Este archivo
├── requirements.txt        Dependencias del orquestador
├── Procfile                Cómo arranca en Railway
├── .env.example            Plantilla de variables
├── orchestrator/           EL CEREBRO
│   ├── main.py             FastAPI: recibe webhooks y coordina
│   ├── config.py           Configuración
│   ├── db.py               Base de datos
│   ├── stripe_handler.py   Pagos (Stripe)
│   ├── railway.py          Despliegue en Railway
│   ├── telegram_factory.py Creación de bots (Managed Bots + pool)
│   └── provisioning.py     Une todo: crear → desplegar → entregar
├── bot_template/           EL BOT que se clona por cliente
│   ├── bot.py              Autoconfigurable (detecta grupo y admin solo)
│   └── requirements.txt
└── docs/
    ├── ARCHITECTURE.md     Cómo encaja todo
    ├── STRIPE_SETUP.md     Configurar Stripe paso a paso
    ├── MANAGED_BOTS.md     Creación automática de bots + plan B
    └── DEPLOYMENT.md       Puesta en producción (lo que haces tú)
```

---

## Probar en local

```bash
cd SaaSBots
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # rellena los valores
uvicorn orchestrator.main:app --reload
```

Abre http://localhost:8000 → debe responder con el estado del servicio.

---

## Estado

| Fase | Estado |
|------|--------|
| 0. Estructura y docs | ✅ Hecho |
| 1. Base de datos | ✅ Hecho |
| 2. Plantilla del bot | ✅ Hecho |
| 3. Automatización Railway | ✅ Hecho |
| 4. Creación de bots | ✅ Hecho (Managed Bots + pool) |
| 5. Stripe | ✅ Hecho |
| 6. Orquestador | ✅ Hecho |
| 7. Producción | 🟡 Requiere tu acción → `docs/DEPLOYMENT.md` |

---

## Lo único que necesitas hacer tú

1. Cuenta de **Stripe** verificada (datos fiscales)
2. **Bot maestro** en BotFather
3. Poner las **claves** en las variables de entorno
4. Desplegar el orquestador en **Railway**

Detalles en `docs/DEPLOYMENT.md`.
