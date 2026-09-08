from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import UserRateThrottle

from .models import Plan, Subscription, PaymentTransaction
from .serializers import (
    PlanSerializer, SubscriptionSerializer,
    CreateOrderSerializer, VerifyPaymentSerializer,
    PaymentTransactionSerializer,
)
from .services import SubscriptionService, PaymentService


class SubscriptionThrottle(UserRateThrottle):
    """
    Per blueprint: max 10 subscription attempts per hour per user.

    Scope-based rather than a hard-coded rate, so every throttle limit lives
    together in DEFAULT_THROTTLE_RATES and can be tuned without a deploy.
    """
    scope = 'subscription'


class PlanListView(generics.ListAPIView):
    """GET /api/v1/plans/ ← List all plans."""
    serializer_class = PlanSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        qs = Plan.objects.filter(is_active=True)
        # Filter by user's role
        user_role = self.request.user.role
        if user_role == 'seeker':
            qs = qs.filter(tier__in=[Plan.Tier.FREE, Plan.Tier.PRO])
        elif user_role == 'recruiter':
            qs = qs.filter(tier__in=[Plan.Tier.FREE, Plan.Tier.BUSINESS])
        return qs.order_by('sort_order')


class MySubscriptionView(APIView):
    """GET /api/v1/subscriptions/me/ ← Current subscription."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        sub = (
            Subscription.objects
            .filter(user=request.user).select_related('plan')
            .order_by('-created_at')
            .first()
        )
        if not sub:
            return Response({
                'subscription': None,
                'has_pro_access': False,
                'message': 'No subscription found.',
            })
        return Response({
            'subscription': SubscriptionSerializer(sub).data,
            'has_pro_access': SubscriptionService.has_pro_access(request.user),
        })


class CreateOrderView(APIView):
    """
    POST /api/v1/subscriptions/create-order/
    Body: { "plan_slug": "pro_monthly" }
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [SubscriptionThrottle]

    def post(self, request):
        serializer = CreateOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = PaymentService.create_order(
            user=request.user,
            plan_slug=serializer.validated_data['plan_slug'],
        )
        return Response(result, status=status.HTTP_201_CREATED)


class VerifyPaymentView(APIView):
    """
    POST /api/v1/subscriptions/verify/
    Body: { razorpay_order_id, razorpay_payment_id, razorpay_signature, plan_slug }
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [SubscriptionThrottle]

    def post(self, request):
        serializer = VerifyPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        subscription = PaymentService.verify_and_activate(
            user=request.user,
            order_id=serializer.validated_data['razorpay_order_id'],
            payment_id=serializer.validated_data['razorpay_payment_id'],
            signature=serializer.validated_data['razorpay_signature'],
            plan_slug=serializer.validated_data['plan_slug'],
        )
        return Response({
            'message': 'Subscription activated successfully!',
            'subscription': SubscriptionSerializer(subscription).data,
        })


class MyPaymentHistoryView(generics.ListAPIView):
    """GET /api/v1/payments/me/ ← Payment transaction history."""
    serializer_class = PaymentTransactionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return PaymentTransaction.objects.filter(user=self.request.user)
    
class MyCapabilitiesView(APIView):
    """
    GET /api/v1/feature-gates/me/

    Full snapshot of the current user's plan, limits, feature flags,
    and live usage. The frontend fetches this once per session and
    renders gated UI (upgrade prompts, locked features, quota meters)
    from it — no client-side plan logic needed.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from .services import FeatureGateService
        return Response(FeatureGateService.get_capabilities(request.user))
    
class CancelSubscriptionView(APIView):
    """
    POST /api/v1/subscriptions/cancel/
    Body: { "reason": "..." } (optional)

    Graceful: trials end immediately; paid plans keep access until
    the current period ends.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from django.utils import timezone

        reason = (request.data.get('reason') or '').strip()
        sub, access_end = SubscriptionService.cancel_subscription(
            request.user,
            reason=reason,
        )
        return Response({
            'message': 'Subscription cancelled.',
            'subscription': SubscriptionSerializer(sub).data,
            'access_until': access_end,
            'note': (
                'You will continue to have access until your current period ends.'
                if access_end and access_end > timezone.now()
                else 'Trial cancelled — access has ended.'
            ),
        })
    
class InvoiceView(APIView):
    """
    GET /api/v1/payments/me/<transaction_id>/invoice/
    Returns structured invoice data for one of the user's own
    successful transactions.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, transaction_id):
        from django.shortcuts import get_object_or_404
        from .invoice import generate_invoice_data

        txn = get_object_or_404(
            PaymentTransaction,
            id=transaction_id,
            user=request.user,
            status=PaymentTransaction.Status.SUCCESS,
        )
        return Response(generate_invoice_data(txn))