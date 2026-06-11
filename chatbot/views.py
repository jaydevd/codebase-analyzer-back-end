from django.shortcuts import render
from rest_framework.views import APIView
from chatbot.serializers import PromptSeriallizer
from rest_framework.permissions import AllowAny, IsAuthenticated
from common.responses import error_response
from rest_framework import status
import agent

# Create your views here.
class PromptView(APIView):
  serializer_class = [PromptSeriallizer]
  permission_classes = [IsAuthenticated]

  def post(self, request):
    serializer = self.serializer_class(data=request.data)

    if not serializer.is_valid():
      return error_response(
          "Invalid request data.",
          status_code=status.HTTP_400_BAD_REQUEST,
      )

    prompt=serializer.validated_data.prompt
    repo_full_name=serializer.validated_data.repo_full_name
    branch=serializer.validated_data.branch

    agent.invoke(prompt, repo_full_name, branch)
    

