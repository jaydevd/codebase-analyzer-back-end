from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from unittest.mock import patch
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


class AuthAPITestCase(APITestCase):
    register_url = "/auth/register/"
    login_url = "/auth/login/"
    refresh_url = "/auth/token/refresh/"
    logout_url = "/auth/logout/"
    me_url = "/auth/user/"
    change_password_url = "/auth/change-password/"
    password_reset_url = "/auth/password-reset/"
    password_reset_confirm_url = "/auth/password-reset/confirm/"

    def create_user(self, **overrides):
        payload = {
            "email": "user@example.com",
            "first_name": "Test",
            "last_name": "User",
            "password": "StrongPass123!",
        }
        payload.update(overrides)
        password = payload.pop("password")
        return User.objects.create_user(password=password, **payload)

    def authenticate(self, user=None):
        user = user or self.create_user()
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
        return user, refresh

    def test_registration_success_sends_welcome_email(self):
        response = self.client.post(
            self.register_url,
            {
                "email": "new@example.com",
                "first_name": "New",
                "last_name": "User",
                "password": "StrongPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(email="new@example.com").exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Welcome", mail.outbox[0].subject)

    def test_registration_rejects_duplicate_email(self):
        self.create_user(email="duplicate@example.com")

        response = self.client.post(
            self.register_url,
            {
                "email": "duplicate@example.com",
                "first_name": "Dup",
                "last_name": "User",
                "password": "StrongPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)

    def test_login_returns_jwt_tokens(self):
        self.create_user(email="login@example.com", password="StrongPass123!")

        response = self.client.post(
            self.login_url,
            {"email": "login@example.com", "password": "StrongPass123!"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data["data"])
        self.assertIn("refresh", response.data["data"])

    def test_login_rejects_inactive_user(self):
        self.create_user(email="inactive@example.com", password="StrongPass123!", is_active=False)

        response = self.client.post(
            self.login_url,
            {"email": "inactive@example.com", "password": "StrongPass123!"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_token_refresh_rotates_tokens(self):
        user = self.create_user(email="refresh@example.com")
        refresh = RefreshToken.for_user(user)

        response = self.client.post(self.refresh_url, {"refresh": str(refresh)}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data["data"])
        self.assertIn("refresh", response.data["data"])

    def test_logout_blacklists_refresh_token(self):
        _, refresh = self.authenticate()

        response = self.client.post(self.logout_url, {"refresh": str(refresh)}, format="json")

        self.assertEqual(response.status_code, status.HTTP_205_RESET_CONTENT)
        with self.assertRaises(TokenError):
            refresh.check_blacklist()

    def test_me_requires_authentication(self):
        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_returns_profile_for_authenticated_user(self):
        user, _ = self.authenticate()

        response = self.client.get(self.me_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["email"], user.email)

    def test_profile_update(self):
        self.authenticate()

        response = self.client.patch(
            self.me_url,
            {"first_name": "Updated", "last_name": "Name"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["first_name"], "Updated")

    def test_change_password_updates_credentials_and_sends_email(self):
        user, _ = self.authenticate()

        response = self.client.post(
            self.change_password_url,
            {"old_password": "StrongPass123!", "new_password": "NewStrongPass123!"},
            format="json",
        )

        user.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(user.check_password("NewStrongPass123!"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("password was changed", mail.outbox[0].subject)

    def test_change_password_rejects_invalid_old_password(self):
        self.authenticate()

        response = self.client.post(
            self.change_password_url,
            {"old_password": "WrongPass123!", "new_password": "NewStrongPass123!"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_password_reset_request_does_not_leak_unknown_email(self):
        response = self.client.post(
            self.password_reset_url,
            {"email": "unknown@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 0)

    def test_password_reset_request_sends_email(self):
        self.create_user(email="reset@example.com")

        response = self.client.post(
            self.password_reset_url,
            {"email": "reset@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Reset your password", mail.outbox[0].subject)

    def test_password_reset_confirm_updates_password(self):
        user = self.create_user(email="confirm@example.com")
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        response = self.client.post(
            self.password_reset_confirm_url,
            {"uid": uid, "token": token, "new_password": "AnotherStrong123!"},
            format="json",
        )

        user.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(user.check_password("AnotherStrong123!"))

    def test_password_reset_confirm_rejects_invalid_token(self):
        user = self.create_user(email="badtoken@example.com")
        uid = urlsafe_base64_encode(force_bytes(user.pk))

        response = self.client.post(
            self.password_reset_confirm_url,
            {"uid": uid, "token": "invalid-token", "new_password": "AnotherStrong123!"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_github_authorize_returns_login_url_for_login_intent(self):
        response = self.client.get("/auth/github/authorize/?intent=login")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("url", response.data["data"])

    def test_github_authorize_requires_auth_for_link_intent(self):
        response = self.client.get("/auth/github/authorize/?intent=link")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("auth.views.GitHubOAuthService.get_user_info")
    @patch("auth.views.GitHubOAuthService.get_verified_primary_email")
    @patch("auth.views.GitHubOAuthService.exchange_code_for_token")
    def test_github_login_links_existing_email_user_without_repo_connection(
        self,
        exchange_code_for_token,
        get_verified_primary_email,
        get_user_info,
    ):
        user = self.create_user(email="github@example.com")
        session = self.client.session
        session["github_oauth_context"] = {
            "state": "github-state",
            "intent": "login",
            "initiating_user_id": None,
            "return_path": "/dashboard",
        }
        session.save()

        exchange_code_for_token.return_value = {"access_token": "github-token"}
        get_user_info.return_value = {
            "id": 101,
            "login": "octocat",
            "avatar_url": "https://example.com/avatar.png",
            "name": "Git Hub",
            "email": "github@example.com",
        }
        get_verified_primary_email.return_value = "github@example.com"

        response = self.client.get("/auth/github/callback/?code=test-code&state=github-state")

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        user.refresh_from_db()
        self.assertEqual(user.github_oauth_id, 101)
        self.assertEqual(user.github_oauth_username, "octocat")
        self.assertFalse(user.is_github_installation_active)
        self.assertIsNone(user.github_installation_id)

    @patch("auth.views.GitHubOAuthService.get_user_info")
    @patch("auth.views.GitHubOAuthService.get_verified_primary_email")
    @patch("auth.views.GitHubOAuthService.exchange_code_for_token")
    def test_github_link_attaches_login_to_authenticated_user(
        self,
        exchange_code_for_token,
        get_verified_primary_email,
        get_user_info,
    ):
        user, _ = self.authenticate()
        session = self.client.session
        session["github_oauth_context"] = {
            "state": "github-link-state",
            "intent": "link",
            "initiating_user_id": str(user.id),
            "return_path": "/user",
        }
        session.save()

        exchange_code_for_token.return_value = {"access_token": "github-token"}
        get_user_info.return_value = {
            "id": 202,
            "login": "linked-octocat",
            "avatar_url": "https://example.com/avatar.png",
            "name": "Linked User",
            "email": "user@example.com",
        }
        get_verified_primary_email.return_value = "user@example.com"

        response = self.client.get("/auth/github/callback/?code=test-code&state=github-link-state")

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn("action=github_login_linked", response.url)
        user.refresh_from_db()
        self.assertEqual(user.github_oauth_id, 202)
        self.assertEqual(user.github_oauth_username, "linked-octocat")

    @patch("auth.views.GitHubOAuthService.get_user_info")
    @patch("auth.views.GitHubOAuthService.get_verified_primary_email")
    @patch("auth.views.GitHubOAuthService.exchange_code_for_token")
    def test_github_link_is_blocked_when_identity_is_already_linked_elsewhere(
        self,
        exchange_code_for_token,
        get_verified_primary_email,
        get_user_info,
    ):
        user, _ = self.authenticate()
        self.create_user(
            email="occupied@example.com",
            github_oauth_id=303,
            github_oauth_username="occupied-user",
        )
        session = self.client.session
        session["github_oauth_context"] = {
            "state": "github-link-conflict",
            "intent": "link",
            "initiating_user_id": str(user.id),
            "return_path": "/user",
        }
        session.save()

        exchange_code_for_token.return_value = {"access_token": "github-token"}
        get_user_info.return_value = {
            "id": 303,
            "login": "occupied-user",
            "avatar_url": "",
            "name": "Occupied User",
            "email": "user@example.com",
        }
        get_verified_primary_email.return_value = "user@example.com"

        response = self.client.get("/auth/github/callback/?code=test-code&state=github-link-conflict")

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn("error=github_login_in_use", response.url)

    def test_set_password_requires_authentication(self):
        response = self.client.post("/auth/set-password/", {"new_password": "NewPass123!"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def create_oauth_user(self, provider="google", **overrides):
        payload = {
            "email": f"{provider}@example.com",
            "first_name": "OAuth",
            "last_name": "User",
        }
        payload.update(overrides)
        user = User(**payload)
        if provider == "google":
            user.google_id = "google-123"
        else:
            user.github_oauth_id = 456
        user.set_unusable_password()
        user.save()
        return user

    def test_set_password_success_for_google_user(self):
        user = self.create_oauth_user(provider="google")
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        response = self.client.post(
            "/auth/set-password/",
            {"new_password": "NewStrongPass123!"},
            format="json",
        )

        user.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(user.has_usable_password())
        self.assertTrue(user.check_password("NewStrongPass123!"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("password was changed", mail.outbox[0].subject)

    def test_set_password_success_for_github_user(self):
        user = self.create_oauth_user(provider="github")
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        response = self.client.post(
            "/auth/set-password/",
            {"new_password": "NewStrongPass123!"},
            format="json",
        )

        user.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(user.check_password("NewStrongPass123!"))

    def test_set_password_rejects_email_password_user(self):
        user, _ = self.authenticate()

        response = self.client.post(
            "/auth/set-password/",
            {"new_password": "NewStrongPass123!"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not_oauth_account", str(response.data))

    def test_set_password_rejects_user_with_existing_password(self):
        user = self.create_oauth_user(provider="google")
        user.set_password("ExistingPass123!")
        user.save()
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        response = self.client.post(
            "/auth/set-password/",
            {"new_password": "NewStrongPass123!"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already_has_password", str(response.data))


    @patch("auth.views.GitHubOAuthService.get_user_info")
    @patch("auth.views.GitHubOAuthService.get_verified_primary_email")
    @patch("auth.views.GitHubOAuthService.exchange_code_for_token")
    def test_github_link_is_blocked_when_email_matches_another_user(
        self,
        exchange_code_for_token,
        get_verified_primary_email,
        get_user_info,
    ):
        user, _ = self.authenticate()
        self.create_user(email="other@example.com")
        session = self.client.session
        session["github_oauth_context"] = {
            "state": "github-email-conflict",
            "intent": "link",
            "initiating_user_id": str(user.id),
            "return_path": "/user",
        }
        session.save()

        exchange_code_for_token.return_value = {"access_token": "github-token"}
        get_user_info.return_value = {
            "id": 404,
            "login": "new-user",
            "avatar_url": "",
            "name": "New User",
            "email": "other@example.com",
        }
        get_verified_primary_email.return_value = "other@example.com"

        response = self.client.get("/auth/github/callback/?code=test-code&state=github-email-conflict")

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn("error=github_email_in_use", response.url)
