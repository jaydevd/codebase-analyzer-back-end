from rest_framework import serializers
from core.models import ChatSession, ChatMessage
from common.constants import MAX_ATTACHED_FILE_BYTES


# ---------------------------------------------------------------------------
# Existing serializers (keep unchanged – used by query flow)
# ---------------------------------------------------------------------------

class AttachedFileSerializer(serializers.Serializer):
    filename = serializers.CharField(required=True)
    content = serializers.CharField(required=True, allow_blank=True)

    def validate_content(self, value):
        if len(value) > MAX_ATTACHED_FILE_BYTES:
            raise serializers.ValidationError("File content exceeds 1MB limit.")
        return value


class QueryHistoryItemSerializer(serializers.Serializer):
    role = serializers.CharField(required=True)
    content = serializers.CharField(required=True, allow_blank=True)


class QueryRequestSerializer(serializers.Serializer):
    prompt = serializers.CharField(required=True, allow_blank=False)
    repo = serializers.CharField(required=True, allow_blank=False)
    branch = serializers.CharField(required=True, allow_blank=False)
    chat_id = serializers.UUIDField(required=True)
    attached_files = AttachedFileSerializer(many=True, required=False, default=list)
    history = QueryHistoryItemSerializer(many=True, required=False, allow_null=True)
    stream = serializers.BooleanField(required=False, default=True)


class SaveChatSerializer(serializers.Serializer):
    session_id = serializers.UUIDField(required=True)
    prompt = serializers.CharField(required=True, allow_blank=False)
    repo = serializers.CharField(required=True, allow_blank=False)
    branch = serializers.CharField(required=True, allow_blank=False)
    content = serializers.CharField(required=True, allow_blank=False)


# ---------------------------------------------------------------------------
# Chat-session serializers
# ---------------------------------------------------------------------------

class ChatSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatSession
        fields = (
            "id",
            "title",
            "repository",
            "branch",
            "created_at",
            "updated_at",
            "is_deleted",
            "is_archived",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class CreateChatSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatSession
        fields = (
            "id",
            "title",
            "repository",
            "branch",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class UpdateChatSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatSession
        fields = ("title", "is_deleted", "is_archived")


# ---------------------------------------------------------------------------
# Chat-message serializers
# ---------------------------------------------------------------------------

class ChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = (
            "id",
            "chat_id",
            "prompt",
            "content",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class ChatSessionDetailSerializer(serializers.ModelSerializer):
    messages = ChatMessageSerializer(many=True, read_only=True)

    class Meta:
        model = ChatSession
        fields = (
            "id",
            "title",
            "repository",
            "branch",
            "created_at",
            "updated_at",
            "is_deleted",
            "is_archived",
            "messages",
        )
        read_only_fields = (
            "id",
            "created_at",
            "updated_at",
            "messages",
        )
