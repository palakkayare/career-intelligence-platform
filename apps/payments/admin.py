from django.contrib import admin, messages
from django.utils.html import format_html

from .models import Plan, Subscription, PaymentTransaction, Refund, WebhookEvent
from .webhook_handlers import process_event


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'tier', 'billing_period', 'price_inr', 'is_active', 'sort_order')
    list_filter = ('tier', 'billing_period', 'is_active')
    search_fields = ('name', 'slug')


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'status', 'current_period_end', 'trial_ends_at', 'created_at')
    list_filter = ('status', 'plan__tier')
    search_fields = ('user__email',)
    raw_id_fields = ('user', 'plan')


class RefundInline(admin.TabularInline):
    model = Refund
    extra = 0
    can_delete = False
    readonly_fields = (
        'amount_inr', 'reason', 'issued_by', 'status',
        'razorpay_refund_id', 'access_revoked', 'failure_reason', 'created_at',
    )
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        # Refunds are issued through the action below, never typed in by hand.
        return False


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user', 'plan', 'amount_inr', 'status', 'refunded_display',
        'razorpay_order_id', 'created_at',
    )
    list_filter = ('status',)
    search_fields = ('user__email', 'razorpay_order_id', 'razorpay_payment_id')
    raw_id_fields = ('user', 'plan', 'subscription')
    inlines = [RefundInline]
    actions = ['refund_selected']

    @admin.display(description='Refunded')
    def refunded_display(self, obj):
        from .services import RefundService
        remaining = RefundService.refundable_amount(obj)
        refunded = obj.amount_inr - remaining
        return f'Rs.{refunded}' if refunded else '-'

    @admin.action(description='Refund selected payments in full')
    def refund_selected(self, request, queryset):
        """
        Full refunds only, and access is revoked with them. Partial refunds
        run through RefundService.issue() directly - they need an amount and
        a judgement call that does not belong in a bulk action.
        """
        from .services import RefundService

        done = failed = 0
        for txn in queryset:
            try:
                RefundService.issue(
                    transaction_obj=txn,
                    reason=f'Refunded from admin by {request.user.email}',
                    actor=request.user,
                )
                done += 1
            except Exception as exc:
                failed += 1
                self.message_user(
                    request, f'Transaction {txn.id}: {exc}', level=messages.ERROR,
                )

        if done:
            self.message_user(
                request, f'{done} payment(s) refunded.', level=messages.SUCCESS,
            )
        if not done and not failed:
            self.message_user(request, 'Nothing to refund.', level=messages.WARNING)


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = (
        'created_at', 'transaction', 'amount_inr', 'status',
        'issued_by', 'access_revoked', 'razorpay_refund_id',
    )
    list_filter = ('status', 'access_revoked', 'created_at')
    search_fields = (
        'razorpay_refund_id', 'transaction__razorpay_payment_id',
        'issued_by__email', 'reason',
    )
    date_hierarchy = 'created_at'
    raw_id_fields = ('transaction', 'issued_by')
    readonly_fields = (
        'transaction', 'amount_inr', 'reason', 'issued_by', 'status',
        'razorpay_refund_id', 'access_revoked', 'failure_reason', 'created_at',
    )

    # Money movements are a record of what happened, not an editable form.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = (
        'razorpay_event_id', 'event_type', 'processing_status',
        'retry_count', 'received_at', 'processed_at',
    )
    list_filter = ('event_type', 'processing_status')
    search_fields = ('razorpay_event_id',)
    readonly_fields = ('formatted_payload', 'received_at', 'processed_at')
    exclude = ('payload',)
    actions = ['retry_processing']

    def formatted_payload(self, obj):
        import json
        pretty = json.dumps(obj.payload, indent=2)
        return format_html('<pre>{}</pre>', pretty)
    formatted_payload.short_description = 'Payload'

    @admin.action(description='Retry processing selected events')
    def retry_processing(self, request, queryset):
        success_count = 0
        fail_count = 0
        for event in queryset:
            try:
                process_event(event)
                event.processing_status = WebhookEvent.ProcessingStatus.PROCESSED
                from django.utils import timezone
                event.processed_at = timezone.now()
                event.error_message = ''
                event.save()
                success_count += 1
            except Exception as e:
                event.processing_status = WebhookEvent.ProcessingStatus.FAILED
                event.error_message = str(e)[:1000]
                event.save()
                fail_count += 1

        self.message_user(
            request,
            f"Retried {queryset.count()} events: {success_count} succeeded, {fail_count} failed.",
        )