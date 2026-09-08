from django.urls import path

from .views import (
    ApplyRewardView,
    LeaderboardView,
    MyCodeView,
    MyRewardsView,
    MyStatsView,
    TrackClickView,
)

referrals_patterns = [
    path('my-code/', MyCodeView.as_view(), name='my-code'),
    path('my-stats/', MyStatsView.as_view(), name='my-stats'),
    path('my-rewards/', MyRewardsView.as_view(), name='my-rewards'),
    path('apply-reward/', ApplyRewardView.as_view(), name='apply-reward'),
    path('track-click/', TrackClickView.as_view(), name='track-click'),
    path('leaderboard/', LeaderboardView.as_view(), name='leaderboard'),
]