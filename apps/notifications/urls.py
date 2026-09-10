from django.urls import path

from .views import (
    DeviceTokenView,
    MarkAllReadView,
    MarkReadView,
    NotificationListView,
    PreferencesView,
    UnreadCountView,
    UnsubscribeView,
)

notifications_patterns = [
    path("", NotificationListView.as_view(), name="list"),
    path("unread-count/", UnreadCountView.as_view(), name="unread-count"),
    path("<int:pk>/mark-read/", MarkReadView.as_view(), name="mark-read"),
    path("mark-all-read/", MarkAllReadView.as_view(), name="mark-all-read"),
    path("device-token/", DeviceTokenView.as_view(), name="device-token"),
]

preferences_patterns = [
    path("me/", PreferencesView.as_view(), name="preferences"),
]

# Public unsubscribe link used inside emails
unsubscribe_patterns = [
    path("<str:token>/", UnsubscribeView.as_view(), name="unsubscribe"),
]
