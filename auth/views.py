import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.shortcuts import redirect
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from auth.oauth import GitHubOAuthService, GoogleOAuthService
from auth.serializers import (
    ChangePasswordSerializer,
    CustomTokenRefreshSerializer,
    GitHubOAuthCallbackQuerySerializer,
    LoginSerializer,
    LogoutSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
    UpdateProfileSerializer,
    UserSerializer,
)
from auth.services import AuthEmailService
from common.responses import error_response, success_response

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        AuthEmailService.send_welcome_email(user)
        return success_response(
            "Registration successful.",
            data=UserSerializer(user).data,
            status_code=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        refresh = RefreshToken.for_user(user)
        data = {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": UserSerializer(user).data,
        }
        return success_response("Login successful.", data=data)


class CustomTokenRefreshView(TokenRefreshView):
    permission_classes = [AllowAny]
    serializer_class = CustomTokenRefreshSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        return success_response("Token refreshed successfully.", data=response.data)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        refresh = RefreshToken(serializer.validated_data["refresh"])
        try:
            refresh.blacklist()
        except AttributeError:
            return error_response(
                "Token blacklisting is not enabled.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return success_response("Logout successful.", status_code=status.HTTP_205_RESET_CONTENT)


class ProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == "PATCH":
            return UpdateProfileSerializer
        return UserSerializer

    def get_object(self):
        return self.request.user

    def retrieve(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object())
        return success_response("User profile fetched successfully.", data=serializer.data)

    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            self.get_object(),
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return success_response(
            "Profile updated successfully.",
            data=UserSerializer(user).data,
        )


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password", "updated_at"])
        AuthEmailService.send_password_changed_email(user)
        return success_response("Password changed successfully.")


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(
            email__iexact=serializer.validated_data["email"],
            is_active=True,
        ).first()
        if user:
            AuthEmailService.send_password_reset_email(user)
        return success_response(
            "If an account exists for this email, a password reset link has been sent."
        )


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password", "updated_at"])
        AuthEmailService.send_password_changed_email(user)
        return success_response("Password has been reset successfully.")


class GoogleAuthorizeView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        state = secrets.token_urlsafe(32)
        request.session["google_oauth_state"] = state
        request.session.set_expiry(600)

        redirect_uri = request.build_absolute_uri("/auth/google/callback/")
        url = GoogleOAuthService.get_authorize_url(state, redirect_uri)
        return redirect(url)


class GoogleCallbackView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        from django.shortcuts import redirect as dj_redirect

        code = request.query_params.get("code")
        state = request.query_params.get("state")
        stored_state = request.session.pop("google_oauth_state", None)

        if not stored_state or state != stored_state:
            return dj_redirect(f"{settings.FRONTEND_URL}/auth/callback?error=invalid_state")

        if not code:
            return dj_redirect(f"{settings.FRONTEND_URL}/auth/callback?error=no_code")

        redirect_uri = request.build_absolute_uri("/auth/google/callback/")
        token_data = GoogleOAuthService.exchange_code_for_token(code, redirect_uri)
        if not token_data or "id_token" not in token_data:
            return dj_redirect(f"{settings.FRONTEND_URL}/auth/callback?error=token_exchange_failed")

        profile = GoogleOAuthService.verify_id_token(token_data["id_token"])
        if not profile:
            return dj_redirect(f"{settings.FRONTEND_URL}/auth/callback?error=invalid_token")
        if not profile.get("email_verified"):
            return dj_redirect(f"{settings.FRONTEND_URL}/auth/callback?error=email_not_verified")

        email = profile["email"].lower()
        google_id = profile["google_id"]

        user = User.objects.filter(google_id=google_id).first()
        if not user:
            user = User.objects.filter(email__iexact=email).first()

        if user:
            changed = False
            if user.google_id != google_id:
                user.google_id = google_id
                changed = True
            avatar = profile.get("avatar_url", "")
            if avatar and user.avatar_url != avatar:
                user.avatar_url = avatar
                changed = True
            if changed:
                user.save(update_fields=["google_id", "avatar_url", "updated_at"])
        else:
            user = User(
                email=email,
                first_name=profile.get("first_name", ""),
                last_name=profile.get("last_name", ""),
                google_id=google_id,
                avatar_url=profile.get("avatar_url", ""),
            )
            user.set_unusable_password()
            user.save()

        refresh = RefreshToken.for_user(user)
        frontend_url = (
            f"{settings.FRONTEND_URL}/auth/callback"
            f"?access={refresh.access_token}&refresh={refresh}"
        )
        return dj_redirect(frontend_url)


class GitHubAuthorizeView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        intent = request.query_params.get("intent", "login")
        if intent not in {"login", "link"}:
            return error_response(
                "Invalid GitHub OAuth intent.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        state = secrets.token_urlsafe(32)

        if intent == "link":
            if not request.user.is_authenticated:
                return error_response(
                    "Authentication is required to link GitHub login.",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )
            User.objects.filter(pk=request.user.pk).update(
                github_oauth_context={
                    "state": state,
                    "intent": intent,
                    "initiating_user_id": str(request.user.id),
                    "return_path": request.query_params.get("return_path") or "/user",
                }
            )
        else:
            request.session["github_oauth_context"] = {
                "state": state,
                "intent": intent,
                "initiating_user_id": None,
                "return_path": request.query_params.get("return_path") or "/user",
            }
            request.session.set_expiry(600)
            request.session.save()

        redirect_uri = request.build_absolute_uri("/auth/github/callback/")
        url = GitHubOAuthService.get_authorize_url(state, redirect_uri)

        if intent == "link":
            return success_response("GitHub authorization URL generated.", data={"url": url})

        return redirect(url)


class GitHubCallbackView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        serializer = GitHubOAuthCallbackQuerySerializer(data=request.query_params)
        if not serializer.is_valid():
            return redirect(self._frontend_url(error="invalid_request"))

        code = serializer.validated_data["code"]
        state = serializer.validated_data["state"]

        oauth_context = request.session.pop("github_oauth_context", None)
        if not oauth_context or state != oauth_context.get("state"):
            user = User.objects.filter(github_oauth_context__contains={"state": state}).first()
            if user and user.github_oauth_context:
                oauth_context = user.github_oauth_context
                User.objects.filter(pk=user.pk).update(github_oauth_context=None)
        if not oauth_context or state != oauth_context.get("state"):
            return redirect(self._frontend_url(error="invalid_state"))

        redirect_uri = request.build_absolute_uri("/auth/github/callback/")
        token_data = GitHubOAuthService.exchange_code_for_token(code, redirect_uri)
        access_token = token_data.get("access_token")
        if not access_token:
            return redirect(self._frontend_url(error="token_exchange_failed"))

        user_info = GitHubOAuthService.get_user_info(access_token)
        github_id = user_info.get("id")
        login = user_info.get("login", "")
        avatar = user_info.get("avatar_url", "")
        name = user_info.get("name", "") or ""
        email = GitHubOAuthService.get_verified_primary_email(access_token, user_info)

        if not github_id:
            return redirect(self._frontend_url(error="invalid_github_user"))

        existing_user = User.objects.filter(github_oauth_id=github_id).first()
        intent = oauth_context.get("intent", "login")

        if intent == "link":
            return self._handle_link_callback(
                oauth_context=oauth_context,
                github_id=github_id,
                login=login,
                avatar=avatar,
                email=email,
                access_token=access_token,
                existing_user=existing_user,
            )

        if not email and not existing_user:
            return redirect(self._frontend_url(error="no_email"))

        normalized_email = email.lower() if email else None
        user = existing_user
        if not user and normalized_email:
            user = User.objects.filter(email__iexact=normalized_email).first()

        if user:
            if user.github_oauth_id and user.github_oauth_id != github_id:
                return redirect(self._frontend_url(error="github_login_replace_requires_unlink"))
            if self._has_github_account_mismatch(user, login):
                return redirect(self._frontend_url(error="github_account_mismatch"))
            self._sync_github_identity(user, github_id, login, avatar, access_token)
        else:
            parts = name.split(" ", 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ""

            user = User(
                email=normalized_email,
                first_name=first_name,
                last_name=last_name,
                github_oauth_id=github_id,
                github_oauth_username=login,
                github_oauth_token=access_token,
                github_username=login,
                avatar_url=avatar,
            )
            user.set_unusable_password()
            user.save()

        refresh = RefreshToken.for_user(user)
        frontend_url = (
            f"{settings.FRONTEND_URL}/auth/callback"
            f"?access={refresh.access_token}&refresh={refresh}"
        )
        return redirect(frontend_url)

    @staticmethod
    def _frontend_url(error=None, action=None, return_path=None):
        query_parts = []
        if error:
            query_parts.append(f"error={error}")
        if action:
            query_parts.append(f"action={action}")
        if return_path:
            query_parts.append(f"return_path={return_path}")
        suffix = f"?{'&'.join(query_parts)}" if query_parts else ""
        return f"{settings.FRONTEND_URL}/auth/callback{suffix}"

    @classmethod
    def _sync_github_identity(cls, user, github_id, login, avatar, access_token):
        user.github_oauth_id = github_id
        user.github_oauth_username = login
        user.github_oauth_token = access_token
        user.github_username = user.github_installation_account_login or login
        if avatar:
            user.avatar_url = avatar
        user.save(
            update_fields=[
                "github_oauth_id",
                "github_oauth_username",
                "github_oauth_token",
                "github_username",
                "avatar_url",
                "updated_at",
            ]
        )

    @staticmethod
    def _has_github_account_mismatch(user, github_login):
        return (
            bool(user.github_installation_account_login)
            and user.github_installation_account_login != github_login
        )

    def _handle_link_callback(
        self,
        *,
        oauth_context,
        github_id,
        login,
        avatar,
        email,
        access_token,
        existing_user,
    ):
        initiating_user_id = oauth_context.get("initiating_user_id")
        user = User.objects.filter(pk=initiating_user_id).first()
        return_path = oauth_context.get("return_path") or "/user"
        if not user:
            return redirect(self._frontend_url(error="link_session_expired"))
        if user.github_oauth_id and user.github_oauth_id != github_id:
            return redirect(self._frontend_url(error="github_login_replace_requires_unlink", return_path=return_path))
        if existing_user and existing_user.pk != user.pk:
            return redirect(self._frontend_url(error="github_login_in_use", return_path=return_path))
        if email:
            normalized_email = email.lower()
            email_owner = User.objects.filter(email__iexact=normalized_email).first()
            if email_owner and email_owner.pk != user.pk:
                return redirect(self._frontend_url(error="github_email_in_use", return_path=return_path))
        if self._has_github_account_mismatch(user, login):
            return redirect(self._frontend_url(error="github_account_mismatch", return_path=return_path))

        self._sync_github_identity(user, github_id, login, avatar, access_token)
        return redirect(
            self._frontend_url(
                action="github_login_linked",
                return_path=return_path,
            )
        )


class GitHubUnlinkView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not user.github_oauth_id:
            return error_response(
                "GitHub login is not linked.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        user.github_oauth_id = None
        user.github_oauth_username = None
        user.github_oauth_token = None
        user.github_username = user.github_installation_account_login
        user.save(
            update_fields=[
                "github_oauth_id",
                "github_oauth_username",
                "github_oauth_token",
                "github_username",
                "updated_at",
            ]
        )
        return success_response(
            "GitHub login unlinked successfully.",
            data=UserSerializer(user).data,
        )
