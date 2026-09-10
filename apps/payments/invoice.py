"""
Invoice generation for successful payment transactions.

This module owns what an invoice *says*; invoice_pdf.py owns how it looks.
Company identity and the GST rate come from settings so they can differ per
environment and a placeholder GSTIN can never quietly ship to production.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings

TWO_PLACES = Decimal("0.01")


def _money(value):
    return str(value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP))


def generate_invoice_data(transaction):
    """
    Build a structured invoice dict for one successful transaction.
    Raises ValueError for non-successful transactions.
    """
    from .models import PaymentTransaction

    if transaction.status != PaymentTransaction.Status.SUCCESS:
        raise ValueError("Cannot generate an invoice for a non-successful transaction")

    # The amount charged is GST-inclusive, so the base is back-calculated
    # from the total. Deriving GST as (total - base) rather than rounding
    # both separately keeps subtotal + GST exactly equal to what was paid.
    rate = Decimal(str(settings.INVOICE_GST_RATE))
    divisor = Decimal("1") + (rate / Decimal("100"))
    base_amount = (transaction.amount_inr / divisor).quantize(
        TWO_PLACES,
        rounding=ROUND_HALF_UP,
    )
    gst = transaction.amount_inr - base_amount

    user = transaction.user
    customer_name = getattr(user, "full_name", "") or user.email

    return {
        "invoice_number": f"INV-{transaction.id:08d}",
        "date": transaction.created_at.strftime("%d %B %Y"),
        "paid_at": transaction.updated_at.strftime("%d %B %Y"),
        "company": {
            "name": settings.INVOICE_COMPANY_NAME,
            "address": settings.INVOICE_COMPANY_ADDRESS,
            "gstin": settings.INVOICE_GSTIN,
        },
        "customer": {
            "email": user.email,
            "name": customer_name,
        },
        "items": [
            {
                "description": f"{transaction.plan.name} Subscription",
                "period": transaction.plan.billing_period,
                "amount": _money(base_amount),
            },
        ],
        "subtotal": _money(base_amount),
        "gst_rate": str(rate.normalize()),
        "gst": _money(gst),
        "total": str(transaction.amount_inr),
        "currency": "INR",
        "payment": {
            "method": "Razorpay",
            "transaction_id": transaction.razorpay_payment_id,
            "order_id": transaction.razorpay_order_id,
        },
    }
