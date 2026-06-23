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
    generate_response_with_history,
)
from rest_framework.permissions import IsAuthenticated
from core.serializers import (
    QueryRequestSerializer,
    CreateChatSessionSerializer,
    ChatSessionSerializer,
    UpdateChatSessionSerializer,
    ChatSessionDetailSerializer,
)
from core.models import ChatSession


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
        should_stream = serializer.validated_data.get("stream", True)

        session = get_object_or_404(
            ChatSession, pk=chat_id, user_id=request.user, is_deleted=False
        )

        owner = user.github_username
        repo = owner + '/' + repo
        print("repo: ", repo)

        try:
            attached_chunks = process_attached_files(attached_files)
            indexed_chunks = search_codebase(prompt, repo, branch)
            print("indexed_chunks: ", indexed_chunks)
            ranked = merge_and_rank(attached_chunks, indexed_chunks)
            code_context = assemble_context(ranked)
            print("context: ", code_context)
            response = generate_response_with_history(
                prompt, code_context, session_id=str(chat_id), stream=should_stream
            )
        except Exception:
            return error_response(
                "Unable to process the query right now.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if should_stream:
            return StreamingHttpResponse(
                response,
                content_type="text/plain",
            )

        return success_response(
            "Query processed successfully.",
            data={"answer": response},
        )


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
