from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

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
                    ("human", "{user_message}"),
                ]
            )
            self._chain = prompt | self.get_chat_model() | StrOutputParser()
        return self._chain

    def stream(self, *, system_prompt: str, user_message: str):
        return self.get_chain().stream(
            {
                "system_prompt": system_prompt,
                "user_message": user_message,
            }
        )

    def invoke(self, *, system_prompt: str, user_message: str) -> str:
        return self.get_chain().invoke(
            {
                "system_prompt": system_prompt,
                "user_message": user_message,
            }
        )


langchain_service = LangChainService()
