import secrets

from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification, NotificationPreferences
from .serializers import (
    DeviceTokenSerializer,
    NotificationSerializer,
    NotificationPreferencesSerializer,
)
from .service import NotificationService


class NotificationListView(generics.ListAPIView):
    """GET /api/v1/notifications/"""

    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Always scoped to the logged-in user, so cross-user access is impossible
        qs = Notification.objects.filter(user=self.request.user)

        # Optional ?unread=true filter for the notification bell dropdown
        if self.request.query_params.get('unread') == 'true':
            qs = qs.filter(is_read=False)
        return qs


class UnreadCountView(APIView):
    """GET /api/v1/notifications/unread-count/"""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        count = NotificationService.unread_count(request.user)
        return Response({'unread_count': count})


class MarkReadView(APIView):
    """POST /api/v1/notifications/<id>/mark-read/"""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        # Filtering by user here means another user's id returns 404, not 403
        notif = get_object_or_404(Notification, pk=pk, user=request.user)
        NotificationService.mark_read(notif, request.user)
        return Response({'message': 'Marked as read'})


class MarkAllReadView(APIView):
    """POST /api/v1/notifications/mark-all-read/"""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        NotificationService.mark_all_read(request.user)
        return Response({'message': 'All marked as read'})


class PreferencesView(generics.RetrieveUpdateAPIView):
    """GET / PATCH /api/v1/notification-preferences/me/"""

    serializer_class = NotificationPreferencesSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        # Created on signup by a signal, but get_or_create keeps older
        # accounts working too
        prefs, _ = NotificationPreferences.objects.get_or_create(
            user=self.request.user,
            defaults={'unsubscribe_token': secrets.token_urlsafe(48)},
        )
        return prefs


class UnsubscribeView(APIView):
    """GET /unsubscribe/<token>/ — public, opened from an email link."""

    permission_classes = [permissions.AllowAny]

    def get(self, request, token):
        prefs = get_object_or_404(NotificationPreferences, unsubscribe_token=token)

        # Turn off every email category. The user can re-enable
        # individual ones from their account settings.
        prefs.email_application_updates = False
        prefs.email_new_matches_digest = False
        prefs.email_payment_events = False
        prefs.email_subscription_alerts = False
        prefs.email_profile_views = False
        prefs.email_marketing = False
        prefs.save()

        return Response({
            'message': (
                'You have been unsubscribed from all email notifications. '
                'You can re-enable specific categories in your account settings.'
            ),
        })


class DeviceTokenView(APIView):
    """
    POST   /api/v1/notifications/device-token/  - register this device
    DELETE /api/v1/notifications/device-token/  - forget it (logout, opt-out)

    The User model has carried fcm_token since Phase 2, but nothing could
    write to it, so mobile push had no way to reach anyone.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = DeviceTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.fcm_token = serializer.validated_data['fcm_token']
        user.save(update_fields=['fcm_token'])

        if serializer.validated_data['enable_push']:
            prefs, _ = NotificationPreferences.objects.get_or_create(user=user)
            prefs.push_enabled = True
            prefs.save(update_fields=['push_enabled'])

        return Response({'detail': 'Device registered for push notifications.'})

    def delete(self, request):
        user = request.user
        user.fcm_token = None
        user.save(update_fields=['fcm_token'])

        prefs = NotificationPreferences.objects.filter(user=user).first()
        if prefs:
            prefs.push_enabled = False
            prefs.save(update_fields=['push_enabled'])

        return Response(status=status.HTTP_204_NO_CONTENT)