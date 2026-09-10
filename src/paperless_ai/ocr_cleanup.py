import logging

from documents.models import Document
from paperless_ai.client import AIClient
from paperless_ai.db import db_connection_released
from paperless_ai.prompts.context import OcrCleanupPromptContext
from paperless_ai.prompts.render import render_prompt

logger = logging.getLogger("paperless_ai.ocr_cleanup")


def get_ai_ocr_cleanup(document: Document) -> str:
    """
    Runs a document's OCR text through the configured LLM to fix obvious
    recognition errors, returning the corrected plain text.
    """
    from llama_index.core.llms import ChatMessage

    prompt = render_prompt(OcrCleanupPromptContext(content=document.content or ""))

    client = AIClient()
    # Hand the pooled DB connection back while the (slow) LLM query runs so it
    # is not pinned for the call's duration; see paperless_ai.db and #12976.
    with db_connection_released():
        with client._normalize_errors():
            result = client.llm.chat([ChatMessage(role="user", content=prompt)])

    return result.message.content.strip()
