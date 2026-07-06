from django.urls import path

from auth.views import (
    ChangePasswordView,
    CustomTokenRefreshView,
    GitHubAuthorizeView,
    GitHubCallbackView,
    GitHubUnlinkView,
    GoogleAuthorizeView,
    GoogleCallbackView,
    LoginView,
    LogoutView,
    ProfileView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    RegisterView,
    SetPasswordView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("token/refresh/", CustomTokenRefreshView.as_view(), name="token-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("user/", ProfileView.as_view(), name="auth-user"),
    path("set-password/", SetPasswordView.as_view(), name="auth-set-password"),
    path("change-password/", ChangePasswordView.as_view(), name="auth-change-password"),
    path("password-reset/", PasswordResetRequestView.as_view(), name="auth-password-reset"),
    path(
        "password-reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="auth-password-reset-confirm",
    ),
    path("google/authorize/", GoogleAuthorizeView.as_view(), name="auth-google-authorize"),
    path("google/callback/", GoogleCallbackView.as_view(), name="auth-google-callback"),
    path("github/authorize/", GitHubAuthorizeView.as_view(), name="auth-github-authorize"),
    path("github/callback/", GitHubCallbackView.as_view(), name="auth-github-callback"),
    path("github/unlink/", GitHubUnlinkView.as_view(), name="auth-github-unlink"),
]
