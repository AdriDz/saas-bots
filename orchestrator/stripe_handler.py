"""
Lógica de Stripe: crear el Checkout (link de pago) y verificar los webhooks.

Modelo de cobro:
  - 25€ pago único (puesta en marcha)  → STRIPE_PRICE_SETUP
  - 5€/mes suscripción recurrente       → STRIPE_PRICE_MONTHLY

Ambos se cobran en el mismo Checkout. El primer mes el cliente paga 25€ + 5€,
y a partir del mes siguiente solo 5€.
"""
import stripe

from . import config

stripe.api_key = config.STRIPE_SECRET_KEY


def crear_checkout(telegram_id: int | None = None) -> str:
    """
    Crea una sesión de Checkout y devuelve la URL de pago.
    El cliente abre esa URL, paga, y Stripe nos avisa por webhook.
    """
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[
            {"price": config.STRIPE_PRICE_MONTHLY, "quantity": 1},   # 5€/mes recurrente
            {"price": config.STRIPE_PRICE_SETUP,   "quantity": 1},   # 25€ una vez
        ],
        # Guardamos el telegram_id para saber a quién entregar el bot
        metadata={"telegram_id": str(telegram_id or "")},
        subscription_data={"metadata": {"telegram_id": str(telegram_id or "")}},
        success_url=f"{config.PUBLIC_URL}/exito?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{config.PUBLIC_URL}/cancelado",
    )
    return session.url


def verificar_webhook(payload: bytes, sig_header: str):
    """
    Verifica la firma del webhook para asegurar que viene de Stripe de verdad.
    Devuelve el evento parseado o lanza excepción si la firma es inválida.
    """
    return stripe.Webhook.construct_event(
        payload, sig_header, config.STRIPE_WEBHOOK_SECRET
    )


def _g(obj, key, default=None):
    """Lee una clave de un objeto de Stripe (StripeObject) o dict de forma segura.

    El SDK de Stripe devuelve StripeObject, que NO soporta `.get()` como un dict
    normal (el acceso a `.get` se interpreta como búsqueda de clave). Por eso
    accedemos siempre por subíndice con manejo de errores.
    """
    try:
        v = obj[key]
    except (KeyError, TypeError):
        return default
    return v if v is not None else default


def datos_checkout_completado(event) -> dict:
    """Extrae los datos relevantes de un evento checkout.session.completed."""
    session = event["data"]["object"]
    cust_details = _g(session, "customer_details", {})
    metadata = _g(session, "metadata", {})
    return {
        "stripe_customer": _g(session, "customer"),
        "stripe_sub": _g(session, "subscription"),
        "email": _g(cust_details, "email", ""),
        "telegram_id": _int_or_none(_g(metadata, "telegram_id")),
    }


def datos_factura(event) -> dict:
    """Extrae datos de eventos invoice.paid / invoice.payment_failed."""
    invoice = event["data"]["object"]
    return {
        "stripe_customer": _g(invoice, "customer"),
        "stripe_sub": _g(invoice, "subscription"),
    }


def datos_suscripcion(event) -> dict:
    """Extrae datos de eventos customer.subscription.*"""
    sub = event["data"]["object"]
    return {
        "stripe_customer": _g(sub, "customer"),
        "stripe_sub": _g(sub, "id"),
        "status": _g(sub, "status"),
    }


def _int_or_none(v):
    try:
        return int(v) if v else None
    except (ValueError, TypeError):
        return None
