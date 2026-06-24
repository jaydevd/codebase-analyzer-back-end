from django.utils import timezone
from django.db import models

# Create your models here.

def get_unix_timestamp() -> int:
    """Return the current UNIX timestamp as an integer."""
    return int(timezone.now().timestamp())