import secrets

from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification, NotificationPreferences
from .serializers import NotificationSerializer, NotificationPreferencesSerializer
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