"""
Wrapper around razorpay SDK.
Centralizes config and provides typed methods.
"""
import razorpay
from django.conf import settings


class RazorpayClient:
    """Singleton-style wrapper."""

    _client = None

    @classmethod
    def get_client(cls):
        if cls._client is None:
            cls._client = razorpay.Client(
                auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
            )
            cls._client.set_app_details({"title": "Career Intelligence", "version": "1.0"})
        return cls._client

    @classmethod
    def create_order(cls, amount_inr, receipt, notes=None):
        """
        Create a Razorpay order.

        Args:
            amount_inr: Decimal/int rupees (e.g., 499)
            receipt: Internal reference (max 40 chars)
            notes: Dict of metadata (visible in Razorpay dashboard)

        Returns: order dict from Razorpay
        """
        client = cls.get_client()
        order = client.order.create({
            'amount': int(amount_inr * 100),  # paise
            'currency': 'INR',
            'receipt': receipt,
            'notes': notes or {},
        })
        return order

    @classmethod
    def verify_payment_signature(cls, order_id, payment_id, signature):
        """
        Verify the cryptographic signature.
        Returns True if valid, raises SignatureVerificationError if not.
        """
        client = cls.get_client()
        client.utility.verify_payment_signature({
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': signature,
        })
        return True

    @classmethod
    def fetch_payment(cls, payment_id):
        """Fetch payment details from Razorpay."""
        client = cls.get_client()
        return client.payment.fetch(payment_id)

    @classmethod
    def fetch_order(cls, order_id):
        """Fetch order details from Razorpay."""
        client = cls.get_client()
        return client.order.fetch(order_id)
    
    @classmethod
    def refund_payment(cls, payment_id, amount_inr=None, notes=None):
        """
        Refund a captured payment.

        Args:
            payment_id: Razorpay payment id to refund
            amount_inr: Decimal/int rupees. None refunds the full amount.
            notes: Dict of metadata (visible in the Razorpay dashboard)

        Returns: refund dict from Razorpay. Refunds are asynchronous - the
        returned status is usually 'pending' and settles later, confirmed by
        the refund.processed webhook.
        """
        client = cls.get_client()
        payload = {'notes': notes or {}}
        if amount_inr is not None:
            payload['amount'] = int(amount_inr * 100)  # paise
        return client.payment.refund(payment_id, payload)

    @classmethod
    def verify_webhook_signature(cls, raw_body, signature, secret=None):
        """
        Verify webhook payload was sent by Razorpay.

        Args:
            raw_body: Raw request body STRING (not parsed JSON)
            signature: Value from X-Razorpay-Signature header
            secret: Webhook secret (defaults to settings)

        Raises SignatureVerificationError on mismatch.
        """
        from django.conf import settings

        secret = secret or settings.RAZORPAY_WEBHOOK_SECRET
        if not secret:
            raise ValueError("Webhook secret not configured")

        client = cls.get_client()
        # Razorpay SDK has this utility
        client.utility.verify_webhook_signature(
            raw_body,
            signature,
            secret,
        )
        return True