from types import SimpleNamespace
from importlib.machinery import ModuleSpec
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from langchain_core.runnables import RunnableLambda
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate
import sys
import types

from core.query import assemble_context
from core.services.langchain_service import LangChainService
from core.views import QueryView


class QueryViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = SimpleNamespace(
            is_authenticated=True,
            id="test-user-id",
            email="query@example.com",
        )

    @patch("core.views.generate_response")
    @patch("core.views.assemble_context")
    @patch("core.views.merge_and_rank")
    @patch("core.views.search_codebase")
    @patch("core.views.process_attached_files")
    def test_post_returns_success_envelope_for_non_stream_request(
        self,
        mock_process_attached_files,
        mock_search_codebase,
        mock_merge_and_rank,
        mock_assemble_context,
        mock_generate_response,
    ):
        mock_process_attached_files.return_value = [{"file_path": "attached.py"}]
        mock_search_codebase.return_value = [{"file_path": "repo.py"}]
        mock_merge_and_rank.return_value = [{"file_path": "repo.py"}]
        mock_assemble_context.return_value = "assembled context"
        mock_generate_response.return_value = "final answer"

        request = self.factory.post(
            "/api/query/",
            {
                "prompt": "How does auth work?",
                "repo": "owner/repo",
                "branch": "main",
                "stream": False,
                "attached_files": [{"filename": "notes.py", "content": "print('x')"}],
                "history": [{"role": "user", "content": "previous question"}],
            },
            format="json",
        )
        force_authenticate(request, user=self.user)
        response = QueryView.as_view()(request)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "Query processed successfully.")
        self.assertEqual(response.data["data"]["answer"], "final answer")
        mock_generate_response.assert_called_once_with(
            "How does auth work?",
            "assembled context",
            stream=False,
        )

    def test_post_rejects_invalid_payload(self):
        request = self.factory.post(
            "/api/query/",
            {"repo": "owner/repo", "branch": "main", "stream": False},
            format="json",
        )
        force_authenticate(request, user=self.user)
        response = QueryView.as_view()(request)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["message"], "Invalid query payload.")
        self.assertIn("prompt", response.data["errors"])


class AssembleContextTests(SimpleTestCase):
    @patch("core.query.tiktoken.get_encoding")
    def test_assemble_context_includes_recent_history_and_code_chunks(self, mock_get_encoding):
        class FakeEncoding:
            @staticmethod
            def encode(value):
                return list(value)

        mock_get_encoding.return_value = FakeEncoding()
        context = assemble_context(
            chunks=[
                {
                    "file_path": "core/views.py",
                    "start_line": 10,
                    "end_line": 20,
                    "text": "def post(self, request):\n    return None",
                }
            ],
            conversation_history=[
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "second"},
            ],
        )

        self.assertIn("## Conversation history", context)
        self.assertIn("user: first", context)
        self.assertIn("assistant: second", context)
        self.assertIn("--- core/views.py (lines 10-20) ---", context)


class LangChainServiceTests(SimpleTestCase):
    @patch("core.services.langchain_service.ANTHROPIC_API_KEY", "anthropic-key")
    @patch("core.services.langchain_service.LLM_PROVIDER", "anthropic")
    @patch("core.services.langchain_service.LLM_MODEL", "claude-3-5-sonnet-latest")
    @patch("core.services.langchain_service.LLM_TEMPERATURE", 0.2)
    @patch("core.services.langchain_service.LLM_MAX_TOKENS", 2048)
    @patch("langchain_anthropic.ChatAnthropic")
    def test_get_chat_model_builds_anthropic_model(self, mock_chat_anthropic):
        service = LangChainService()
        service.get_chat_model()

        mock_chat_anthropic.assert_called_once_with(
            model="claude-3-5-sonnet-latest",
            api_key="anthropic-key",
            temperature=0.2,
            max_tokens=2048,
        )

    @patch("core.services.langchain_service.GOOGLE_API_KEY", "google-key")
    @patch("core.services.langchain_service.LLM_PROVIDER", "google")
    @patch("core.services.langchain_service.LLM_MODEL", "gemini-2.5-pro")
    @patch("core.services.langchain_service.LLM_TEMPERATURE", 0.1)
    @patch("core.services.langchain_service.LLM_MAX_TOKENS", 1024)
    @patch("langchain_google_genai.ChatGoogleGenerativeAI")
    def test_get_chat_model_builds_google_model(self, mock_chat_google):
        service = LangChainService()
        service.get_chat_model()

        mock_chat_google.assert_called_once_with(
            model="gemini-2.5-pro",
            google_api_key="google-key",
            temperature=0.1,
            max_output_tokens=1024,
        )

    @patch("core.services.langchain_service.OPENAI_API_KEY", "openai-key")
    @patch("core.services.langchain_service.LLM_PROVIDER", "openai")
    @patch("core.services.langchain_service.LLM_MODEL", "gpt-4.1")
    @patch("core.services.langchain_service.LLM_TEMPERATURE", 0.3)
    @patch("core.services.langchain_service.LLM_MAX_TOKENS", 3072)
    def test_get_chat_model_builds_openai_model(self):
        fake_module = types.ModuleType("langchain_openai")
        fake_module.__spec__ = ModuleSpec("langchain_openai", loader=None)
        mock_chat_openai = Mock()
        fake_module.ChatOpenAI = mock_chat_openai
        original_module = sys.modules.get("langchain_openai")
        sys.modules["langchain_openai"] = fake_module
        self.addCleanup(
            lambda: sys.modules.__setitem__("langchain_openai", original_module)
            if original_module is not None
            else sys.modules.pop("langchain_openai", None)
        )

        service = LangChainService()
        service.get_chat_model()

        mock_chat_openai.assert_called_once_with(
            model="gpt-4.1",
            api_key="openai-key",
            temperature=0.3,
            max_tokens=3072,
        )

    @patch("core.services.langchain_service.LLM_PROVIDER", "unsupported")
    def test_get_chat_model_raises_for_unsupported_provider(self):
        service = LangChainService()

        with self.assertRaisesMessage(
            ValueError,
            "Unsupported LLM provider 'unsupported'. Supported providers: anthropic, google, openai.",
        ):
            service.get_chat_model()

    @patch("core.services.langchain_service.ANTHROPIC_API_KEY", "")
    @patch("core.services.langchain_service.LLM_PROVIDER", "anthropic")
    def test_get_chat_model_raises_for_missing_provider_api_key(self):
        service = LangChainService()

        with self.assertRaisesMessage(
            ValueError,
            "Missing API key for provider 'anthropic'.",
        ):
            service.get_chat_model()

    @patch.object(LangChainService, "get_chat_model", return_value=RunnableLambda(lambda payload: payload["user_message"]))
    def test_get_chain_is_cached(self, mock_get_chat_model):
        service = LangChainService()

        first_chain = service.get_chain()
        second_chain = service.get_chain()

        self.assertIs(first_chain, second_chain)
        mock_get_chat_model.assert_called_once()
