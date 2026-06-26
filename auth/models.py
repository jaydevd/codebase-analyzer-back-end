import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from common.models import get_unix_timestamp

class Role(models.TextChoices):
    ADMIN = "admin", "Admin"
    MANAGER = "manager", "Manager"
    USER = "user", "User"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("The email field is required.")

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.USER)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.BigIntegerField(default=get_unix_timestamp(), editable=False)
    updated_at = models.BigIntegerField(default=get_unix_timestamp())

    github_installation_id = models.IntegerField(null=True, blank=True)
    github_username = models.CharField(max_length=255, null=True, blank=True)
    github_installation_account_login = models.CharField(max_length=255, null=True, blank=True)
    github_installation_access_token = models.CharField(max_length=255, null=True, blank=True)
    github_installation_state = models.CharField(max_length=64, null=True, blank=True)
    is_github_installation_active = models.BooleanField(default=False)

    # OAuth login fields
    google_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    github_oauth_id = models.IntegerField(null=True, blank=True, unique=True)
    github_oauth_username = models.CharField(max_length=255, null=True, blank=True)
    github_oauth_token = models.TextField(null=True, blank=True)
    github_oauth_context = models.JSONField(null=True, blank=True)
    avatar_url = models.URLField(max_length=500, null=True, blank=True)

    is_deleted = models.BooleanField(default=False)
    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.email

    @property
    def is_github_login_linked(self):
        return bool(self.github_oauth_id)

    @property
    def is_github_repo_connected(self):
        return bool(self.is_github_installation_active and self.github_installation_id)
