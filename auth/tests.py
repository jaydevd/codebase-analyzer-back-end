from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
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
    me_url = "/auth/me/"
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
