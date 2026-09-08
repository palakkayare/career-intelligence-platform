"""
Invoice generation for successful payment transactions.

Phase 2: returns structured data the frontend renders as HTML.
A later phase can turn this into a PDF and email it.
"""
from decimal import Decimal


def generate_invoice_data(transaction):
    """
    Build a structured invoice dict for one successful transaction.
    Raises ValueError for non-successful transactions.
    """
    from .models import PaymentTransaction

    if transaction.status != PaymentTransaction.Status.SUCCESS:
        raise ValueError('Cannot generate an invoice for a non-successful transaction')

    # Indian GST is 18%; the paid amount is treated as GST-inclusive,
    # so we back-calculate the base amount from the total.
    base_amount = transaction.amount_inr / Decimal('1.18')
    gst = transaction.amount_inr - base_amount

    return {
        'invoice_number': f'INV-{transaction.id:08d}',
        'date': transaction.created_at.strftime('%d %B %Y'),
        'paid_at': transaction.updated_at.strftime('%d %B %Y'),
        'company': {
            'name': 'Career Intelligence Platform Pvt Ltd',
            'address': 'Bangalore, India',
            'gstin': 'XXAAAAA1234A1Z5',  # TODO: replace with the real GSTIN
        },
        'customer': {
            'email': transaction.user.email,
            'name': getattr(transaction.user, 'full_name', '') or transaction.user.email,
        },
        'items': [
            {
                'description': f'{transaction.plan.name} Subscription',
                'period': transaction.plan.billing_period,
                'amount': str(base_amount.quantize(Decimal('0.01'))),
            },
        ],
        'subtotal': str(base_amount.quantize(Decimal('0.01'))),
        'gst': str(gst.quantize(Decimal('0.01'))),
        'total': str(transaction.amount_inr),
        'currency': 'INR',
        'payment': {
            'method': 'Razorpay',
            'transaction_id': transaction.razorpay_payment_id,
            'order_id': transaction.razorpay_order_id,
        },
    }