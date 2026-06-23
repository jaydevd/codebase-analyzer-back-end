from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables.history import RunnableWithMessageHistory

from common.constants import (
    ANTHROPIC_API_KEY,
    GOOGLE_API_KEY,
    OPENAI_API_KEY,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LLM_PROVIDER,
    LLM_TEMPERATURE,
)


class LangChainService:
    def __init__(self):
        self._chain = None
        self._chain_with_history = None
        self._provider_builders = {
            "anthropic": self._build_anthropic_model,
            "google": self._build_google_model,
            "openai": self._build_openai_model,
        }

    def _validate_api_key(self, provider: str, api_key: str):
        if api_key:
            return
        raise ValueError(f"Missing API key for provider '{provider}'.")

    def _build_anthropic_model(self):
        self._validate_api_key("anthropic", ANTHROPIC_API_KEY)

        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=LLM_MODEL,
            api_key=ANTHROPIC_API_KEY,
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        )

    def _build_google_model(self):
        self._validate_api_key("google", GOOGLE_API_KEY)

        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=LLM_MODEL,
            google_api_key=GOOGLE_API_KEY,
            temperature=LLM_TEMPERATURE,
            max_output_tokens=LLM_MAX_TOKENS,
        )

    def _build_openai_model(self):
        self._validate_api_key("openai", OPENAI_API_KEY)

        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=LLM_MODEL,
            api_key=OPENAI_API_KEY,
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        )

    def get_chat_model(self):
        builder = self._provider_builders.get(LLM_PROVIDER)
        if builder is None:
            supported_providers = ", ".join(sorted(self._provider_builders))
            raise ValueError(
                f"Unsupported LLM provider '{LLM_PROVIDER}'. "
                f"Supported providers: {supported_providers}."
            )
        return builder()

    def get_chain(self):
        if self._chain is None:
            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", "{system_prompt}"),
                    ("placeholder", "{chat_history}"),
                    ("human", "Relevant code context:\n{code_context}\n\nUser question: {input}"),
                ]
            )
            self._chain = prompt | self.get_chat_model() | StrOutputParser()
        return self._chain

    def _get_session_history(self, session_id: str):
        from core.services.chat_history import DjangoChatMessageHistory
        return DjangoChatMessageHistory(session_id)

    def get_chain_with_history(self):
        if self._chain_with_history is None:
            self._chain_with_history = RunnableWithMessageHistory(
                self.get_chain(),
                self._get_session_history,
                input_messages_key="input",
                history_messages_key="chat_history",
            )
        return self._chain_with_history

    def stream_with_history(self, *, system_prompt: str, code_context: str, input: str, session_id: str):
        return self.get_chain_with_history().stream(
            {
                "system_prompt": system_prompt,
                "code_context": code_context,
                "input": input,
            },
            config={"configurable": {"session_id": session_id}},
        )

    def invoke_with_history(self, *, system_prompt: str, code_context: str, input: str, session_id: str) -> str:
        return self.get_chain_with_history().invoke(
            {
                "system_prompt": system_prompt,
                "code_context": code_context,
                "input": input,
            },
            config={"configurable": {"session_id": session_id}},
        )

langchain_service = LangChainService()
