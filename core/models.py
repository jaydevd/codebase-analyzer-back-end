from django.db import models
from django.conf import settings
from common.models import get_unix_timestamp
import uuid

class ChatSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_sessions"
    )
    title = models.CharField(max_length=255, default="Untitled Chat")
    repository = models.CharField(max_length=512, null=True, blank=True)
    branch = models.CharField(max_length=256, null=True, blank=True)
    created_at = models.BigIntegerField(default=get_unix_timestamp, editable=False)
    updated_at = models.BigIntegerField(default=get_unix_timestamp)
    is_deleted = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return str(self.id)


class ChatMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chat_id = models.ForeignKey(
        ChatSession, on_delete=models.CASCADE, related_name="messages"
    )
    prompt = models.TextField()
    content = models.TextField(default="No content found")
    created_at = models.BigIntegerField(default=get_unix_timestamp, editable=False)
    updated_at = models.BigIntegerField(default=get_unix_timestamp)

    class Meta:
        ordering = ("created_at",)

    def __str__(self):
        return str(self.chat_id)
