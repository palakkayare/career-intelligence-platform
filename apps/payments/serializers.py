from rest_framework import serializers

from .models import Plan, Subscription, PaymentTransaction


class PlanSerializer(serializers.ModelSerializer):
    period_days = serializers.IntegerField(read_only=True)
    is_paid = serializers.BooleanField(read_only=True)

    class Meta:
        model = Plan
        fields = (
            'id', 'name', 'slug', 'description',
            'tier', 'billing_period',
            'price_inr', 'features',
            'period_days', 'is_paid',
        )
        read_only_fields = fields


class SubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)
    is_active = serializers.SerializerMethodField()
    days_remaining = serializers.IntegerField(read_only=True)

    class Meta:
        model = Subscription
        fields = (
            'public_id', 'plan', 'status',
            'trial_ends_at', 'current_period_start', 'current_period_end',
            'cancelled_at', 'auto_renew',
            'is_active', 'days_remaining',
            'created_at',
        )
        read_only_fields = fields

    def get_is_active(self, obj):
        return obj.is_currently_active()


class CreateOrderSerializer(serializers.Serializer):
    plan_slug = serializers.SlugField(max_length=120)


class VerifyPaymentSerializer(serializers.Serializer):
    razorpay_order_id = serializers.CharField(max_length=100)
    razorpay_payment_id = serializers.CharField(max_length=100)
    razorpay_signature = serializers.CharField(max_length=512)
    plan_slug = serializers.SlugField(max_length=120)


class PaymentTransactionSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source='plan.name', read_only=True)

    class Meta:
        model = PaymentTransaction
        fields = (
            'id', 'plan_name', 'amount_inr', 'status',
            'razorpay_order_id', 'razorpay_payment_id',
            'failure_reason', 'created_at',
        )
        read_only_fields = fields