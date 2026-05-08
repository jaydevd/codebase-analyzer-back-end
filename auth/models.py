from django.db import models
import uuid
from validators import phone_number_validator

class Role(models.TextChoices):
    ADMIN = "admin", "Admin"
    MANAGER = "manager", "Manager"
    USER = "user", "User"

# Create your models here.
class User:
  id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

  email = models.EmailField(unique=True)
  first_name = models.CharField(max_length=255)
  last_name = models.CharField(max_length=255)
  primary_phone_number = models.CharField(max_length=10, blank=True, default="", validators=[phone_number_validator])
  alternate_phone_number = models.CharField(max_length=10, blank=True, default="", validators=[phone_number_validator])
  role = models.CharField(max_length=20, choices=Role.choices, default=Role.USER)

  is_active = models.BooleanField(default=True)
  is_staff = models.BooleanField(default=False)

  USERNAME_FIELD = "email"
  EMAIL_FIELD = "email"
  REQUIRED_FIELDS = []

  def __str__(self):
      return self.email