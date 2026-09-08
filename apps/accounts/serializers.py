"""
Serializers - convert between Python objects and JSON.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    """
    Validate and create a new user.
    """
    password = serializers.CharField(
        write_only=True,               # Never return this in the response
        required=True,
        validators=[validate_password],  # Django's built-in password validators
    )
    password_confirm = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = ('email', 'password', 'password_confirm', 'role')
        extra_kwargs = {
            'role': {'required': True},
        }

    def validate_role(self, value):
        """Don't let public registration create admin users."""
        if value == User.Role.ADMIN:
            raise serializers.ValidationError("Cannot register as admin.")
        return value

    def validate(self, attrs):
        """Check both passwords match."""
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({
                'password_confirm': "Passwords don't match."
            })
        return attrs

    def create(self, validated_data):
        """Use our custom manager to create the user (handles password hashing)."""
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        user = User.objects.create_user(
            password=password,
            **validated_data,
        )

        # Attach the referral if a `ref` code came with the request
        request = self.context.get('request')
        if request:
            ref_code = request.data.get('ref') or request.query_params.get('ref')
            if ref_code:
                try:
                    from apps.referrals.services import ReferralService

                    ReferralService.attach_referral_on_signup(
                        referee_user=user,
                        code_str=ref_code,
                        ip_address=self._get_client_ip(request),
                    )
                except Exception as exc:
                    # A broken referral must never block a signup
                    import logging

                    logging.getLogger(__name__).error(
                        f"Referral attach failed: {exc}"
                    )

        return user

    @staticmethod
    def _get_client_ip(request):
        """Extract the real client IP, considering proxies."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')


class UserSerializer(serializers.ModelSerializer):
    """
    Public-facing user representation. Used for /auth/me/.
    """
    class Meta:
        model = User
        fields = ('public_id', 'email', 'role','auth_provider',
            'full_name',
            'profile_picture_url', 'is_email_verified', 'is_2fa_enabled','date_joined')
        read_only_fields = fields  # No editing allowed via this serializer
        
class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Login serializer with custom claims and history tracking."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['role'] = user.role
        token['email'] = user.email
        token['is_email_verified'] = user.is_email_verified
        return token

    def validate(self, attrs):
        # Track login attempts (both success and failure)
        request = self.context.get('request')
        ip = self._get_client_ip(request) if request else None
        ua = request.META.get('HTTP_USER_AGENT', '')[:500] if request else ''

        try:
            data = super().validate(attrs)
        except Exception:
            # Failed login — record it
            from .models import LoginHistory
            LoginHistory.objects.create(
                email_attempted=attrs.get('email', ''),
                status=LoginHistory.Status.FAILED,
                ip_address=ip,
                user_agent=ua,
            )
            raise

        # Success — record it
        from .models import LoginHistory
        LoginHistory.objects.create(
            user=self.user,
            email_attempted=self.user.email,
            status=LoginHistory.Status.SUCCESS,
            ip_address=ip,
            user_agent=ua,
        )

        data['user'] = UserSerializer(self.user).data
        return data

    @staticmethod
    def _get_client_ip(request):
        """Extract the real client IP, considering proxies."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')
    
class VerifyOTPSerializer(serializers.Serializer):
    """For email verification."""
    email = serializers.EmailField()
    code = serializers.CharField(min_length=6, max_length=6)


class ResendOTPSerializer(serializers.Serializer):
    """For requesting a new OTP."""
    email = serializers.EmailField()
    
class PasswordResetRequestSerializer(serializers.Serializer):
    """Request a password reset email."""
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Confirm password reset with token + new password."""
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(
        write_only=True,
        validators=[validate_password],
    )
    new_password_confirm = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({
                'new_password_confirm': "Passwords don't match."
            })
        return attrs

    def validate_uid(self, value):
        """Decode the user ID from base64."""
        try:
            uid = force_str(urlsafe_base64_decode(value))
            self.user = User.objects.get(pk=uid)
        except (User.DoesNotExist, ValueError, TypeError):
            raise serializers.ValidationError("Invalid reset link.")
        return value

    def validate_token(self, value):
        """Verify the token using Django's built-in generator."""
        if not hasattr(self, 'user'):
            raise serializers.ValidationError("Invalid reset link.")
        if not default_token_generator.check_token(self.user, value):
            raise serializers.ValidationError("Reset link expired or invalid.")
        return value

    def save(self):
        self.user.set_password(self.validated_data['new_password'])
        self.user.save()
        return self.user
    
class LoginHistorySerializer(serializers.ModelSerializer):
    class Meta:
        from .models import LoginHistory
        model = LoginHistory
        fields = ('id', 'status', 'ip_address', 'user_agent', 'created_at')
        read_only_fields = fields
        
class GoogleAuthSerializer(serializers.Serializer):
    """Accepts Google ID token from frontend."""
    id_token = serializers.CharField(required=True)
    role = serializers.ChoiceField(
        choices=[('seeker', 'Seeker'), ('recruiter', 'Recruiter')],
        default='seeker',
        required=False,
    )


class AccountDeactivationSerializer(serializers.Serializer):
    """For POST /auth/me/deactivate/"""
    # Optional here rather than in the field, because OAuth accounts have no
    # password to confirm. The service decides whether one is required.
    password = serializers.CharField(
        required=False, allow_blank=True, write_only=True, style={'input_type': 'password'},
    )
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)
    confirm = serializers.BooleanField()

    def validate_confirm(self, value):
        if not value:
            raise serializers.ValidationError(
                'You must confirm that you want to close your account.'
            )
        return value