from django.urls import path

from .views import (
    MyProgressView,
    PointsHistoryView,
    RedeemPerkView,
    WeeklyGoalView,
)

gamification_patterns = [
    path('me/', MyProgressView.as_view(), name='my-progress'),
    path('points/', PointsHistoryView.as_view(), name='points'),
    path('goals/', WeeklyGoalView.as_view(), name='goals'),
    path('perks/redeem/', RedeemPerkView.as_view(), name='redeem-perk'),
]
