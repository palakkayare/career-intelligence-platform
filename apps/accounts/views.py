"""
Authentication views.
"""

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .models import OTPCode
from .serializers import (
    AccountDeactivationSerializer,
    GoogleAuthSerializer,
    LoginHistorySerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
    ResendOTPSerializer,
    UserSerializer,
    VerifyOTPSerializer,
)
from .services import GoogleOAuthService, OTPService, PendingAuthService, TwoFactorAuthService
from .throttles import (
    LoginThrottle,
    OTPRequestThrottle,
    PasswordResetThrottle,
    RegisterThrottle,
    TwoFAThrottle,
)

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    """
    POST /api/v1/auth/register/
    Public endpoint - anyone can register as seeker or recruiter.
    """

    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]  # Public endpoint
    throttle_classes = [RegisterThrottle]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Return user info (not the registration serializer with password fields)
        response_serializer = UserSerializer(user)
        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )


class MeView(APIView):
    """
    GET /api/v1/auth/me/
    Returns the currently authenticated user.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)


class LoginView(APIView):
    """
    POST /api/v1/auth/login/
    Step 1: email + password
    If 2FA enabled → returns { 2fa_required: true, pending_token }
    If 2FA disabled → returns { access, refresh, user }
    """

    permission_classes = [permissions.AllowAny]
    throttle_classes = [LoginThrottle]

    def post(self, request):
        email = request.data.get("email", "").strip().lower()
        password = request.data.get("password", "")

        if not email or not password:
            return Response(
                {"error": "Email and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Authenticate (Django built-in)
        user = authenticate(request, email=email, password=password)

        # Track attempt
        ip = self._get_client_ip(request)
        ua = request.META.get("HTTP_USER_AGENT", "")[:500]

        if not user:
            from .models import LoginHistory

            LoginHistory.objects.create(
                email_attempted=email,
                status=LoginHistory.Status.FAILED,
                ip_address=ip,
                user_agent=ua,
            )
            return Response(
                {"error": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # 2FA enabled? → return pending token, NOT JWT
        if user.is_2fa_enabled:
            pending_token = PendingAuthService.create_token(user)
            return Response(
                {
                    "2fa_required": True,
                    "pending_token": pending_token,
                    "message": "Enter your 2FA code or backup code.",
                },
                status=status.HTTP_200_OK,
            )

        # No 2FA → issue full JWT directly
        return self._issue_tokens(user, request, ip, ua)

    def _issue_tokens(self, user, request, ip, ua):
        """Issue access + refresh JWT and log success."""
        refresh = RefreshToken.for_user(user)
        refresh["role"] = user.role
        refresh["email"] = user.email
        refresh["is_email_verified"] = user.is_email_verified

        # Track success
        from .models import LoginHistory

        LoginHistory.objects.create(
            user=user,
            email_attempted=user.email,
            status=LoginHistory.Status.SUCCESS,
            ip_address=ip,
            user_agent=ua,
        )

        # Update last_login
        from django.utils import timezone

        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])

        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _get_client_ip(request):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")


class Verify2FALoginView(APIView):
    """
    POST /api/v1/auth/2fa/verify-login/
    Step 2 of 2FA login.
    Body: { pending_token, code }
    """

    permission_classes = [permissions.AllowAny]
    throttle_classes = [LoginThrottle]

    def post(self, request):
        pending_token = request.data.get("pending_token")
        code = request.data.get("code", "").strip()

        if not pending_token or not code:
            return Response(
                {"error": "pending_token and code are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate pending token (raises on invalid)
        user = PendingAuthService.verify_token(pending_token)

        # Verify TOTP or backup code
        if not TwoFactorAuthService.verify_login_code(user, code):
            from .models import LoginHistory

            LoginHistory.objects.create(
                user=user,
                email_attempted=user.email,
                status=LoginHistory.Status.FAILED,
                ip_address=self._get_client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
            )
            return Response(
                {"error": "Invalid 2FA code."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Issue full JWT
        ip = self._get_client_ip(request)
        ua = request.META.get("HTTP_USER_AGENT", "")[:500]

        refresh = RefreshToken.for_user(user)
        refresh["role"] = user.role
        refresh["email"] = user.email
        refresh["is_email_verified"] = user.is_email_verified

        from .models import LoginHistory

        LoginHistory.objects.create(
            user=user,
            email_attempted=user.email,
            status=LoginHistory.Status.SUCCESS,
            ip_address=ip,
            user_agent=ua,
        )

        from django.utils import timezone

        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])

        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _get_client_ip(request):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")


class TwoFactorSetupView(APIView):
    """
    POST /api/v1/auth/2fa/setup/
    Authenticated. Initiates 2FA setup, returns QR code.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if request.user.is_2fa_enabled:
            return Response(
                {"error": "2FA is already enabled. Disable first to re-setup."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = TwoFactorAuthService.initiate_setup(request.user)
        return Response(data, status=status.HTTP_200_OK)


class TwoFactorVerifySetupView(APIView):
    """
    POST /api/v1/auth/2fa/verify-setup/
    Authenticated. Body: { code: "123456" }
    Verifies first code → enables 2FA → returns backup codes.
    """

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [TwoFAThrottle]

    def post(self, request):
        code = request.data.get("code", "").strip()

        if not code:
            return Response(
                {"error": "Code is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        backup_codes = TwoFactorAuthService.verify_and_enable(request.user, code)

        return Response(
            {
                "message": "2FA enabled successfully.",
                "backup_codes": backup_codes,
                "warning": "Save these codes in a safe place. They will NOT be shown again.",
            },
            status=status.HTTP_200_OK,
        )


class TwoFactorDisableView(APIView):
    """
    POST /api/v1/auth/2fa/disable/
    Authenticated. Body: { password: "..." }
    Requires password re-confirmation.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        password = request.data.get("password", "")

        if not password:
            return Response(
                {"error": "Password is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        TwoFactorAuthService.disable(request.user, password)

        return Response(
            {"message": "2FA disabled successfully."},
            status=status.HTTP_200_OK,
        )


class RegenerateBackupCodesView(APIView):
    """
    POST /api/v1/auth/2fa/backup-codes/regenerate/
    Authenticated. Returns 10 fresh backup codes.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        codes = TwoFactorAuthService.regenerate_backup_codes(request.user)
        return Response(
            {
                "backup_codes": codes,
                "warning": "Save these codes. Old codes are now invalid.",
            },
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    """
    POST /api/v1/auth/logout/
    Blacklists the refresh token so it can't be used again.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response(
                {"error": "Refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {"message": "Logout successful."},
            status=status.HTTP_200_OK,
        )


class VerifyEmailView(APIView):
    """
    POST /api/v1/auth/verify-email/
    Body: { "email": "...", "code": "123456" }
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        code = serializer.validated_data["code"]

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Don't reveal whether the email exists — generic error
            return Response(
                {"error": "Invalid email or code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Already verified?
        if user.is_email_verified:
            return Response(
                {"message": "Email already verified."},
                status=status.HTTP_200_OK,
            )

        # Verify OTP (raises ValidationError on failure)
        OTPService.verify(
            user=user,
            code=code,
            purpose=OTPCode.Purpose.EMAIL_VERIFICATION,
        )

        # Mark verified
        user.is_email_verified = True
        user.save(update_fields=["is_email_verified"])

        return Response(
            {"message": "Email verified successfully."},
            status=status.HTTP_200_OK,
        )


class ResendOTPView(APIView):
    """
    POST /api/v1/auth/resend-otp/
    Body: { "email": "..." }
    """

    permission_classes = [permissions.AllowAny]
    throttle_classes = [OTPRequestThrottle]

    def post(self, request):
        serializer = ResendOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]

        # Generic response — no email enumeration
        generic_response = Response(
            {"message": "If your email is registered, you will receive a code."},
            status=status.HTTP_200_OK,
        )

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return generic_response

        if user.is_email_verified:
            return Response(
                {"message": "Email already verified."},
                status=status.HTTP_200_OK,
            )

        try:
            OTPService.create_and_send(
                user=user,
                purpose=OTPCode.Purpose.EMAIL_VERIFICATION,
            )
        except ValidationError as e:
            # Cooldown error — show the actual message
            return Response(
                {"error": str(e.detail[0])},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        return generic_response


class PasswordResetRequestView(APIView):
    """
    POST /api/v1/auth/password/reset/
    Body: { "email": "..." }
    """

    permission_classes = [permissions.AllowAny]
    throttle_classes = [PasswordResetThrottle]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]

        # Generic response — prevents email enumeration
        generic_response = Response(
            {"message": "If your email is registered, a reset link was sent."},
            status=status.HTTP_200_OK,
        )

        try:
            user = User.objects.get(email=email, is_active=True)
        except User.DoesNotExist:
            return generic_response  # Silent

        # Generate token + uid
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        # Build reset URL (frontend handles the actual page)
        from django.conf import settings

        frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:3000")
        reset_url = f"{frontend_url}/reset-password?uid={uid}&token={token}"

        # Send email
        body = render_to_string(
            "accounts/password_reset.txt",
            {
                "user": user,
                "reset_url": reset_url,
            },
        )
        send_mail(
            subject="Reset your password",
            message=body,
            from_email=None,
            recipient_list=[user.email],
            fail_silently=False,
        )

        return generic_response


class PasswordResetConfirmView(APIView):
    """
    POST /api/v1/auth/password/reset/confirm/
    Body: { "uid": "...", "token": "...", "new_password": "...", "new_password_confirm": "..." }
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            {"message": "Password reset successful. Please log in."},
            status=status.HTTP_200_OK,
        )


class LoginHistoryView(generics.ListAPIView):
    """
    GET /api/v1/auth/login-history/
    Returns last 50 login attempts for the current user.
    """

    serializer_class = LoginHistorySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        from .models import LoginHistory

        return LoginHistory.objects.filter(
            Q(user=self.request.user) | Q(email_attempted=self.request.user.email)
        ).order_by("-created_at")[:50]


class GoogleAuthView(APIView):
    """
    POST /api/v1/auth/google/
    Body: { "id_token": "<google id token>", "role": "seeker" (optional) }
    Returns our own JWT (access + refresh) plus user info.
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = GoogleAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        google_token = serializer.validated_data["id_token"]
        role = serializer.validated_data.get("role", "seeker")

        # Verify Google token + get/create user
        user, created = GoogleOAuthService.authenticate(google_token, role=role)

        # Issue OUR JWT
        refresh = RefreshToken.for_user(user)
        refresh["role"] = user.role
        refresh["email"] = user.email
        refresh["is_email_verified"] = user.is_email_verified

        # Track login
        from .models import LoginHistory

        ip = self._get_client_ip(request)
        ua = request.META.get("HTTP_USER_AGENT", "")[:500]
        LoginHistory.objects.create(
            user=user,
            email_attempted=user.email,
            status=LoginHistory.Status.SUCCESS,
            ip_address=ip,
            user_agent=ua,
        )

        # Update last login
        from django.utils import timezone

        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])

        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
                "created": created,  # True if new user signed up
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _get_client_ip(request):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")


class DataExportView(APIView):
    """
    GET /api/v1/auth/me/export/

    Everything the platform holds about the requesting user, as JSON.
    Available at any time, not only when closing the account.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from .privacy import DataExportService

        data = DataExportService.build(request.user)

        response = Response(data)
        if request.query_params.get("download") == "true":
            filename = f"my-data-{request.user.public_id}.json"
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class AccountDeactivationView(APIView):
    """
    POST /api/v1/auth/me/deactivate/

    Closes the account: withdraws live applications, stops billing, revokes
    every session and hides the profile. The record is soft-deleted rather
    than removed, so payment and application history survives for the other
    parties involved. Only an admin can restore it.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from .privacy import AccountDeactivationService

        serializer = AccountDeactivationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        summary = AccountDeactivationService.deactivate(
            user=request.user,
            password=serializer.validated_data.get("password"),
            reason=serializer.validated_data.get("reason", ""),
        )

        return Response(
            {
                "detail": "Your account has been closed.",
                "summary": summary,
            },
            status=status.HTTP_200_OK,
        )
