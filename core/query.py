import tiktoken
from typing import Generator
from qdrant_client.models import Filter, FieldCondition, MatchValue
import traceback
from common.constants import (
    QDRANT_COLLECTION,
    qdrant,
    voyage_client,
    VOYAGE_EMBEDDING_MODEL,
)
from embeddings.services.embed import embedding_service
from core.services.langchain_service import langchain_service

MAX_CONTEXT_TOKENS = 150000

SYSTEM_PROMPT = (
    "You are a codebase analysis assistant. Answer the user's question using only "
    "the provided code context. If the context doesn't contain enough information, "
    "say so explicitly rather than guessing. Always reference file paths and line "
    "numbers when citing code."
)


def process_attached_files(files: list[dict]) -> list[dict]:
    chunks = []
    for f in files:
        file_chunks = embedding_service.chunk_file(f["filename"], f["content"])
        for c in file_chunks:
            c["source"] = "attached"
            c["priority"] = 0
        chunks.extend(file_chunks)
    return chunks


def search_codebase(
    prompt: str, repo: str, branch: str, top_k: int = 8
) -> list[dict]:
    result = voyage_client.embed(
        [prompt],
        model=VOYAGE_EMBEDDING_MODEL,
        input_type="query",
    )
    query_vector = result.embeddings[0]

    query_filter = Filter(
        must=[
            FieldCondition(key="repo", match=MatchValue(value=repo)),
            FieldCondition(key="branch", match=MatchValue(value=branch)),
        ]
    )

    response = qdrant.query_points(
        collection_name=QDRANT_COLLECTION,
        query=query_vector,
        query_filter=query_filter,
        limit=top_k,
        with_payload=True,
        with_vectors=False,
    )

    results = []
    for hit in response.points:
        payload = hit.payload or {}
        results.append(
            {
                "source": "indexed",
                "file_path": payload["file_path"],
                "start_line": payload["start_line"],
                "end_line": payload["end_line"],
                "text": payload["text"],
                "score": hit.score,
                "priority": 1,
            }
        )
    return results


def merge_and_rank(
    attached_chunks: list[dict], indexed_chunks: list[dict]
) -> list[dict]:
    combined = attached_chunks + indexed_chunks
    return sorted(combined, key=lambda c: (c["priority"], -c.get("score", 0)))


def assemble_context(
    chunks: list[dict], conversation_history: list[dict] = None
) -> str:
    enc = tiktoken.get_encoding("cl100k_base")
    remaining = MAX_CONTEXT_TOKENS

    parts = []

    if conversation_history:
        history_lines = []
        for turn in conversation_history[-5:]:
            role = turn.get("role", "unknown")
            content = turn.get("content", "")
            history_lines.append(f"{role}: {content}")
        history_section = (
            "## Conversation history\n" + "\n".join(history_lines) + "\n\n"
        )
        history_tokens = len(enc.encode(history_section))
        remaining -= history_tokens
        parts.append(history_section)

    code_parts = []
    for chunk in chunks:
        formatted = (
            f"--- {chunk['file_path']} (lines {chunk['start_line']}-{chunk['end_line']}) ---\n"
            f"{chunk['text']}\n\n"
        )
        token_count = len(enc.encode(formatted))
        if token_count > remaining:
            break
        code_parts.append(formatted)
        remaining -= token_count

    parts.append("## Relevant code\n" + "".join(code_parts))
    return "".join(parts)


def generate_response(
    prompt: str, context: str, stream: bool = True
) -> str | Generator[str, None, None]:
    
    try:
        user_message = f"{context}\n\n## User question\n{prompt}"

        if stream:
            return langchain_service.stream(
                system_prompt=SYSTEM_PROMPT,
                user_message=user_message,
            )

        return langchain_service.invoke(
            system_prompt=SYSTEM_PROMPT,
            user_message=user_message,
        )
    except Exception as e:
        print("something went wrong...")
        traceback.print_exc()
        return None
