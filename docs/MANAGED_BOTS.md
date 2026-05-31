# 🤖 Managed Bots — creación automática de bots

## El problema que resuelve

Antes, crear un bot de Telegram requería hablar a mano con @BotFather:
escribir `/newbot`, ponerle nombre, copiar el token... No se podía automatizar.
Era el único cuello de botella de toda tu idea.

## La solución (Bot API 9.6, abril 2026)

Telegram añadió **Managed Bots**: un "bot maestro" con el permiso `can_manage_bots`
puede crear y controlar bots hijos en nombre del usuario. El cliente solo da
**dos toques** para confirmar y el bot queda creado, sin tocar BotFather.

---

## Cómo activar el permiso en el bot maestro

1. Habla con @BotFather
2. Abre su Mini App de gestión (Bot Management)
3. Activa **Bot Management Mode** para tu bot maestro
4. A partir de ahí, `getMe` devuelve `can_manage_bots: true`

El módulo `telegram_factory.check_can_manage_bots()` comprueba esto.

---

## El flujo automático

```
1. Cliente paga → el orquestador le manda un botón "🤖 Crear mi bot"
   (telegram_factory.send_create_bot_button)
       │
       ▼
2. El cliente pulsa → Telegram abre una pantalla pre-rellenada
       │
       ▼
3. Cliente confirma (2 toques) → se crea el bot
       │
       ▼
4. Llega un update con ManagedBotCreated al webhook /webhook/telegram
       │
       ▼
5. El orquestador llama a getManagedBotToken → obtiene el token
       │
       ▼
6. Con ese token, despliega el bot en Railway (provisioning.provision_bot)
```

### Métodos de la API usados
- `getMe` → comprobar `can_manage_bots`
- `getManagedBotToken(bot_id)` → obtener el token del bot creado
- `replaceManagedBotToken(bot_id)` → rotar el token (seguridad)
- Botón `request_managed_bot` en el teclado → lanza la creación

---

## ⚠️ Plan B: pool de bots pre-creados (FALLBACK MANUAL)

La API de Managed Bots es **muy nueva** (abril 2026) y puede que:
- Las librerías aún no la soporten del todo
- Tarde en estar disponible para todas las cuentas
- Tenga límites de cuántos bots puedes crear

**Por si acaso, el sistema tiene un plan B que funciona seguro:**

### Cómo montar el pool

1. Crea a mano con @BotFather varios bots (p. ej. 20):
   `vip_bot_001`, `vip_bot_002`... (2 minutos cada uno)
2. Crea la tabla del pool en la base de datos:

```sql
CREATE TABLE IF NOT EXISTS bot_pool (
    id          SERIAL PRIMARY KEY,
    bot_id      BIGINT,
    username    TEXT,
    token       TEXT,
    assigned    BOOLEAN DEFAULT FALSE,
    assigned_at TIMESTAMPTZ
);
```

3. Inserta los bots que creaste:

```sql
INSERT INTO bot_pool (bot_id, username, token) VALUES
  (111, 'vip_bot_001', 'TOKEN_1'),
  (222, 'vip_bot_002', 'TOKEN_2');
  -- etc.
```

### Cómo funciona

Cuando un cliente paga, `telegram_factory.asignar_del_pool()` coge un bot libre,
lo marca como asignado y lo despliega. **De cara al cliente sigue siendo automático.**
Tú solo rellenas el pool de vez en cuando (5 min cada X ventas).

El orquestador (`main.py`) ya intenta el pool primero, y si está vacío usa Managed Bots.
Puedes empezar con el pool (funciona 100% hoy) y migrar a Managed Bots cuando esté maduro.

---

## Recomendación

**Arranca con el pool de bots pre-creados.** Es lo más fiable y lo tienes funcionando
desde el día 1. Cuando hayas validado que el negocio funciona y Managed Bots esté
más estable, te pasas a creación 100% automática sin tocar nada del resto del sistema.
