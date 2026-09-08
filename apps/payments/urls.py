from django.urls import path

from .views import (
    PlanListView,
    MySubscriptionView,
    CreateOrderView,
    VerifyPaymentView,
    MyPaymentHistoryView,
    MyCapabilitiesView,
    CancelSubscriptionView,
    InvoiceView,
)
from .webhooks import razorpay_webhook

plans_patterns = [
    path('', PlanListView.as_view(), name='plan-list'),
]

subscriptions_patterns = [
    path('me/', MySubscriptionView.as_view(), name='my-subscription'),
    path('create-order/', CreateOrderView.as_view(), name='create-order'),
    path('verify/', VerifyPaymentView.as_view(), name='verify'),
    # Graceful cancel: trials end instantly, paid plans keep access
    # until the current period ends (auto_renew turned off).
    path('cancel/', CancelSubscriptionView.as_view(), name='cancel'),
]

payments_patterns = [
    path('me/', MyPaymentHistoryView.as_view(), name='my-payments'),
    # Structured invoice data for one successful transaction
    path('me/<int:transaction_id>/invoice/', InvoiceView.as_view(), name='invoice'),
]

webhooks_patterns = [
    path('razorpay/', razorpay_webhook, name='razorpay-webhook'),
]

# Feature gates — capability snapshot for the frontend
feature_gates_patterns = [
    path('me/', MyCapabilitiesView.as_view(), name='my-capabilities'),
]