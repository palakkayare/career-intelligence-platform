from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    AccountDeactivationView,
    DataExportView,
    RegisterView,
    LoginView,
    LogoutView,
    MeView,
    VerifyEmailView,
    ResendOTPView,
    PasswordResetRequestView,
    PasswordResetConfirmView,
    LoginHistoryView,
    GoogleAuthView,
    Verify2FALoginView,
    TwoFactorSetupView,
    TwoFactorVerifySetupView,
    TwoFactorDisableView,
    RegenerateBackupCodesView,
)

app_name = 'accounts'

urlpatterns = [
    # Registration & login
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),

    # Email verification
    path('verify-email/', VerifyEmailView.as_view(), name='verify-email'),
    path('resend-otp/', ResendOTPView.as_view(), name='resend-otp'),

    # Password reset
    path('password/reset/', PasswordResetRequestView.as_view(), name='password-reset'),
    path('password/reset/confirm/', PasswordResetConfirmView.as_view(), name='password-reset-confirm'),

    # Profile
    path('me/', MeView.as_view(), name='me'),
    path('login-history/', LoginHistoryView.as_view(), name='login-history'),

    # Privacy: data portability and account closure
    path('me/export/', DataExportView.as_view(), name='data-export'),
    path('me/deactivate/', AccountDeactivationView.as_view(), name='deactivate'),
    
    # Google Auth
    path('google/', GoogleAuthView.as_view(), name='google-auth'),
    
    # 2FA
    path('2fa/setup/', TwoFactorSetupView.as_view(), name='2fa-setup'),
    path('2fa/verify-setup/', TwoFactorVerifySetupView.as_view(), name='2fa-verify-setup'),
    path('2fa/verify-login/', Verify2FALoginView.as_view(), name='2fa-verify-login'),
    path('2fa/disable/', TwoFactorDisableView.as_view(), name='2fa-disable'),
    path('2fa/backup-codes/regenerate/', RegenerateBackupCodesView.as_view(), name='2fa-backup-codes-regenerate'),
]