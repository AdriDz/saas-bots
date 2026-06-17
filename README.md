# 🤖 SaaS Bots — Plataforma de venta y despliegue automático de bots de Telegram

Plataforma **SaaS llave en mano**: un cliente paga y, **sin intervención manual**, recibe
su propio bot de Telegram para gestionar su canal VIP, desplegado en la nube y con su
propia base de datos. El cobro mensual y la suspensión por impago también son automáticos.

> **El reto técnico**: convertir "una venta" en "un bot nuevo, aislado y en producción"
> sin que un humano tenga que tocar nada. Esto implica orquestar pagos, creación de bots,
> aprovisionamiento de infraestructura y entrega, todo encadenado.

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-database-4169E1?logo=postgresql&logoColor=white)
![Stripe](https://img.shields.io/badge/Stripe-payments-635BFF?logo=stripe&logoColor=white)
![Railway](https://img.shields.io/badge/Deploy-Railway-0B0D0E?logo=railway&logoColor=white)

---

## 🔄 Cómo funciona

```
Cliente paga (Stripe)
        │  webhook
        ▼
┌─────────────────────────┐
│   ORQUESTADOR (FastAPI)  │
│  1. Crea el bot          │ → BotFather / pool de bots gestionados
│  2. Aprovisiona infra    │ → Railway (servicio + PostgreSQL)
│  3. Despliega plantilla  │ → clona AdriDz/bot-template
│  4. Entrega al cliente   │ → instrucciones automáticas
└─────────────────────────┘
        │  cada mes
        ▼
  Cobra la cuota · si falla → pausa el bot
```

1. El cliente paga (pago inicial + suscripción mensual vía **Stripe**).
2. El **orquestador** recibe el webhook y crea el bot de Telegram.
3. Lo **despliega en Railway** con una base de datos PostgreSQL propia.
4. Se lo **entrega al cliente** con instrucciones, listo para usar.
5. Cada mes **cobra la cuota**; si el cliente deja de pagar, **pausa el bot** solo.

---

## 🧱 Arquitectura

El repo separa **el cerebro** (orquestador) de **el producto** (plantilla de bot):

```
SaaSBots/
├── orchestrator/            # EL CEREBRO — coordina todo el ciclo de vida
│   ├── main.py              # FastAPI: webhooks de Stripe y endpoints
│   ├── stripe_handler.py    # Pagos y suscripciones
│   ├── railway.py           # Despliegue/gestión vía API de Railway
│   ├── telegram_factory.py  # Creación de bots (managed bots + pool)
│   ├── provisioning.py      # Encadena: crear → desplegar → entregar
│   ├── db.py / config.py    # Persistencia y configuración
├── bot_template/            # EL PRODUCTO — bot que se clona por cliente
│   └── bot.py               # Autoconfigurable (detecta su grupo y admin)
└── docs/                    # Arquitectura, Stripe, managed bots, despliegue
```

---

## 🛠️ Stack técnico

| Capa | Tecnología |
|------|------------|
| API / orquestación | **FastAPI** (async) + Uvicorn |
| Pagos | **Stripe** (Checkout + webhooks + suscripciones) |
| Infraestructura programática | **Railway** API (crea servicios y bases de datos) |
| Base de datos | **PostgreSQL** |
| Bots | **python-telegram-bot** |
| Despliegue | Railway (Procfile) |

---

## 💡 Lo interesante a nivel de ingeniería

- **Infraestructura como producto**: el orquestador habla con la API de Railway para
  crear servicios y bases de datos bajo demanda — cada cliente queda **aislado**.
- **Disparado por webhooks**: el flujo arranca desde eventos de Stripe, no desde clics.
- **Plantilla autoconfigurable**: el bot clonado se configura solo al añadirlo a un grupo,
  evitando configuración manual por cliente.
- **Ciclo de vida completo**: alta, cobro recurrente y baja/suspensión automáticas.

---

## 🚀 Probar en local

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # rellena los valores
uvicorn orchestrator.main:app --reload
```

Abre <http://localhost:8000> → responde con el estado del servicio.

Variables necesarias (ver `.env.example`): claves de Stripe, token del bot maestro,
token de Railway y la cadena de PostgreSQL. **Nada de esto se commitea** — `.env` está
en `.gitignore`.

---

## 📚 Documentación

| Documento | Contenido |
|-----------|-----------|
| `ROADMAP.md` | Visión general y fases del proyecto |
| `docs/ARCHITECTURE.md` | Cómo encaja cada pieza |
| `docs/STRIPE_SETUP.md` | Configuración de Stripe paso a paso |
| `docs/MANAGED_BOTS.md` | Creación automática de bots (y plan B con pool) |
| `docs/DEPLOYMENT.md` | Puesta en producción |

---

## 👤 Autor

**Adrián Díaz-Rullo Redondo** — Desarrollador Multiplataforma
[github.com/AdriDz](https://github.com/AdriDz)
