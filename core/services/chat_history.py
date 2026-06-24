from typing import List

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

from core.models import ChatMessage


class DjangoChatMessageHistory(BaseChatMessageHistory):
    """LangChain chat history backed by the ChatMessage model."""

    def __init__(self, session_id: str):
        self.session_id = session_id

    @property
    def messages(self) -> List[BaseMessage]:
        chat_msgs = ChatMessage.objects.filter(
            chat_id=self.session_id,
        ).order_by("created_at")

        result: List[BaseMessage] = []
        for msg in chat_msgs:
            if msg.prompt:
                result.append(HumanMessage(content=msg.prompt))
            if msg.content and msg.content != "No content found":
                result.append(AIMessage(content=msg.content))
        return result

    def add_message(self, message: BaseMessage) -> None:
        if isinstance(message, HumanMessage):
            ChatMessage.objects.create(
                chat_id_id=self.session_id,
                prompt=message.content,
                content="No content found",
            )
        elif isinstance(message, AIMessage):
            last = (
                ChatMessage.objects.filter(
                    chat_id_id=self.session_id, content="No content found"
                )
                .order_by("-created_at")
                .first()
            )
            if last:
                last.content = message.content
                last.save(update_fields=["content", "updated_at"])

    def clear(self) -> None:
        ChatMessage.objects.filter(chat_id_id=self.session_id).delete()
