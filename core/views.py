from rest_framework import status
from rest_framework.views import APIView
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from auth.models import User

from common.responses import error_response, success_response
from core.query import (
    process_attached_files,
    search_codebase,
    merge_and_rank,
    assemble_context,
    generate_response,
)
from rest_framework.permissions import IsAuthenticated, AllowAny
from core.serializers import (
    QueryRequestSerializer,
    SaveChatSerializer,
    CreateChatSessionSerializer,
    ChatSessionSerializer,
    UpdateChatSessionSerializer,
    ChatSessionDetailSerializer,
)
from core.models import ChatSession, ChatMessage


def _save_on_complete(stream_generator, message):
    """Streaming generator wrapper that persists the full response on completion."""
    full = []
    for chunk in stream_generator:
        full.append(chunk)
        yield chunk
    message.content = "".join(full)
    message.save(update_fields=["content", "updated_at"])


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

class QueryView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = QueryRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                "Invalid query payload.",
                status_code=status.HTTP_400_BAD_REQUEST,
                errors=serializer.errors,
            )
        user_email = request.user
        user = User.objects.get(email=user_email)

        chat_id = serializer.validated_data["chat_id"]
        prompt = serializer.validated_data["prompt"]
        repo = serializer.validated_data["repo"]
        branch = serializer.validated_data["branch"]
        attached_files = serializer.validated_data.get("attached_files", [])
        history = serializer.validated_data.get("history")
        should_stream = serializer.validated_data.get("stream", True)

        # Validate session exists and belongs to this user
        session = get_object_or_404(
            ChatSession, pk=chat_id, user_id=request.user, is_deleted=False
        )

        owner = user.github_username
        repo = owner + '/' + repo

        # Persist the message immediately (content will be filled after LLM)
        message = ChatMessage.objects.create(
            chat_id=session, prompt=prompt, content=""
        )

        try:
            attached_chunks = process_attached_files(attached_files)
            indexed_chunks = search_codebase(prompt, repo, branch)
            ranked = merge_and_rank(attached_chunks, indexed_chunks)
            context = assemble_context(ranked, history)
            print("context:", context)
            response = generate_response(prompt, context, stream=should_stream)
        except Exception:
            return error_response(
                "Unable to process the query right now.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if should_stream:
            return StreamingHttpResponse(
                _save_on_complete(response, message),
                content_type="text/plain",
            )

        # Non-streaming: update message content and return
        message.content = response
        message.save(update_fields=["content", "updated_at"])
        return success_response(
            "Query processed successfully.",
            data={"answer": response},
        )


# ---------------------------------------------------------------------------
# Chat Session CRUD
# ---------------------------------------------------------------------------

class CreateChatSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreateChatSessionSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Invalid request payload",
                status_code=status.HTTP_400_BAD_REQUEST,
                errors=serializer.errors,
            )
        session = serializer.save(user_id=request.user)
        output = ChatSessionSerializer(session).data
        return success_response(
            message="Chat session created",
            data=output,
            status_code=status.HTTP_201_CREATED,
        )


class GetChatHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sessions = ChatSession.objects.filter(
            user_id=request.user, is_deleted=False
        )
        serializer = ChatSessionSerializer(sessions, many=True)
        return success_response(
            message="Chat history fetched successfully",
            data=serializer.data,
        )


class ChatSessionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        session = get_object_or_404(
            ChatSession, pk=pk, user_id=request.user, is_deleted=False
        )
        serializer = ChatSessionDetailSerializer(session)
        return success_response(
            message="Chat session fetched successfully",
            data=serializer.data,
        )

    def patch(self, request, pk):
        session = get_object_or_404(
            ChatSession, pk=pk, user_id=request.user, is_deleted=False
        )
        serializer = UpdateChatSessionSerializer(
            session, data=request.data, partial=True
        )
        if not serializer.is_valid():
            return error_response(
                message="Invalid request payload",
                status_code=status.HTTP_400_BAD_REQUEST,
                errors=serializer.errors,
            )
        updated = serializer.save()
        output = ChatSessionSerializer(updated).data
        return success_response(
            message="Chat session updated successfully",
            data=output,
        )
