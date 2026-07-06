from django.contrib.auth import authenticate, get_user_model, password_validation
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken, TokenError

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    github_username = serializers.SerializerMethodField()
    is_github_login_linked = serializers.SerializerMethodField()
    is_github_repo_connected = serializers.SerializerMethodField()
    has_password = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "role",
            "is_active",
            "created_at",
            "updated_at",
            "last_login",
            "is_github_installation_active",
            "is_github_login_linked",
            "is_github_repo_connected",
            "github_username",
            "github_oauth_username",
            "github_installation_account_login",
            "google_id",
            "github_oauth_id",
            "avatar_url",
            "has_password",
        )
        read_only_fields = (
            "id",
            "email",
            "role",
            "is_active",
            "created_at",
            "updated_at",
            "last_login",
            "google_id",
            "github_oauth_id",
            "avatar_url",
        )

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_github_username(self, obj):
        return obj.github_installation_account_login or obj.github_oauth_username or obj.github_username

    @extend_schema_field(serializers.BooleanField())
    def get_is_github_login_linked(self, obj):
        return obj.is_github_login_linked

    @extend_schema_field(serializers.BooleanField())
    def get_is_github_repo_connected(self, obj):
        return obj.is_github_repo_connected

    @extend_schema_field(serializers.BooleanField())
    def get_has_password(self, obj):
        return obj.has_usable_password()


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    class Meta:
        model = User
        fields = (
            "email",
            "first_name",
            "last_name",
            "password",
        )

    def validate_email(self, value):
        normalized = User.objects.normalize_email(value).lower()
        if User.objects.filter(email__iexact=normalized).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return normalized

    def validate_password(self, value):
        password_validation.validate_password(value)
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        return User.objects.create_user(password=password, **validated_data)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    default_error_messages = {
        "invalid_credentials": "Invalid email or password.",
        "inactive": "This account is inactive.",
    }

    def validate(self, attrs):
        email = User.objects.normalize_email(attrs["email"]).lower()
        password = attrs["password"]
        user = authenticate(
            request=self.context.get("request"),
            username=email,
            password=password,
        )

        if not user:
            self.fail("invalid_credentials")
        if not user.is_active:
            self.fail("inactive")

        attrs["user"] = user
        return attrs


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()

    def validate_refresh(self, value):
        try:
            RefreshToken(value)
        except TokenError as exc:
            raise serializers.ValidationError("Invalid refresh token.") from exc
        return value


class UpdateProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("first_name", "last_name")


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect.")
        return value

    def validate_new_password(self, value):
        password_validation.validate_password(value, self.context["request"].user)
        return value


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return User.objects.normalize_email(value).lower()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    default_error_messages = {
        "invalid_token": "The password reset link is invalid or has expired.",
    }

    def validate_new_password(self, value):
        user = self._get_user()
        password_validation.validate_password(value, user)
        return value

    def validate(self, attrs):
        user = self._get_user(attrs["uid"])
        token = attrs["token"]
        if not user or not default_token_generator.check_token(user, token):
            self.fail("invalid_token")
        attrs["user"] = user
        return attrs

    def _get_user(self, uid=None):
        uid = uid or self.initial_data.get("uid")
        if not uid:
            return None
        try:
            user_id = force_str(urlsafe_base64_decode(uid))
            return User.objects.filter(pk=user_id, is_active=True).first()
        except (TypeError, ValueError, OverflowError):
            return None


class SetPasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    default_error_messages = {
        "not_oauth_account": "This account was not created via Google or GitHub. Use the change-password endpoint instead.",
        "already_has_password": "This account already has a password set.",
    }

    def validate_new_password(self, value):
        user = self.context["request"].user

        if not user.google_id and not user.github_oauth_id:
            self.fail("not_oauth_account")

        if user.has_usable_password():
            self.fail("already_has_password")

        password_validation.validate_password(value, user)
        return value


class GitHubOAuthCallbackQuerySerializer(serializers.Serializer):
    code = serializers.CharField(required=True)
    state = serializers.CharField(required=True)


class CustomTokenRefreshSerializer(TokenRefreshSerializer):
    default_error_messages = {
        "no_active_account": "Token is invalid or expired.",
    }
