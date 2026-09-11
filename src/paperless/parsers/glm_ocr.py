"""
GLM-OCR: OCR via a local vision-capable LLM served by Ollama (default model
"glm-4v"), run as an independent, on-demand comparison path -- not as a
competing parser in the registry.

This intentionally does NOT participate in normal document consumption
(Tesseract is always what produces the stored Document.content). Instead,
``run_glm_ocr()`` is invoked directly by ``documents.tasks.run_glm_ocr_comparison``,
dispatched in parallel with the normal upload so a doctor can compare both
engines' output side by side on the UKK document-processing page and choose
which one to keep.
"""

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger("paperless.parsing.glm_ocr")

# PDFs are rasterised to one PNG per page at this resolution before being
# sent to the model; other supported MIME types are already images and are
# sent to the model as-is.
_RASTER_DPI = 200

_OCR_PROMPT = (
    "Transcribe all text visible in this image exactly as it appears. "
    "Preserve line breaks and reading order. Do not translate, summarize, "
    "interpret, or add any commentary -- output only the transcribed text."
)


class GlmOcrConfig:
    """Holds the GLM-OCR engine configuration, read from env/settings only.

    Unlike ``RemoteOCRConfig``, this has no per-install database override --
    it is a simpler, deployment-wide toggle configured via environment
    variables (``PAPERLESS_GLM_OCR_*``).
    """

    def __init__(self) -> None:
        self.enabled: bool = settings.GLM_OCR_ENABLED
        self.endpoint: str = settings.GLM_OCR_ENDPOINT
        self.model: str = settings.GLM_OCR_MODEL
        self.request_timeout: int = settings.GLM_OCR_REQUEST_TIMEOUT
        self.allow_internal_endpoints: bool = settings.GLM_OCR_ALLOW_INTERNAL_ENDPOINTS

    def is_valid(self) -> bool:
        """Return True when GLM-OCR is enabled and minimally configured."""
        return self.enabled and bool(self.endpoint) and bool(self.model)


def run_glm_ocr(document_path: Path, mime_type: str, tempdir: Path) -> str:
    """Send each page of *document_path* to the GLM-OCR model and return the text.

    Parameters
    ----------
    document_path:
        Absolute path to the file to OCR.
    mime_type:
        Detected MIME type of the file.
    tempdir:
        Directory to render page images into. Caller owns its lifecycle
        (creation and cleanup).

    Raises
    ------
    Exception
        Any failure (invalid config, blocked endpoint, rasterisation
        failure, Ollama/network error) propagates to the caller.
    """
    config = GlmOcrConfig()
    if not config.is_valid():
        raise RuntimeError("GLM-OCR is not configured")

    from paperless.network import validate_outbound_http_url

    validate_outbound_http_url(
        config.endpoint,
        allow_internal=config.allow_internal_endpoints,
    )

    images = _render_pages(document_path, mime_type, tempdir)
    if not images:
        raise RuntimeError("No page images produced for GLM-OCR")

    from ollama import Client

    client = Client(host=config.endpoint, timeout=config.request_timeout)

    page_texts = []
    for image_path in images:
        response = client.chat(
            model=config.model,
            messages=[
                {
                    "role": "user",
                    "content": _OCR_PROMPT,
                    "images": [image_path],
                },
            ],
        )
        page_text = (response.message.content or "").strip()
        if page_text:
            page_texts.append(page_text)

    return "\n\n".join(page_texts)


def _render_pages(document_path: Path, mime_type: str, tempdir: Path) -> list[Path]:
    """Rasterise *document_path* to one PNG per page for the vision model.

    Non-PDF inputs are already images and are returned as a single-item
    list unchanged. Uses Ghostscript directly (already a dependency via
    ocrmypdf) rather than adding a new rasterisation library.
    """
    if mime_type != "application/pdf":
        return [document_path]

    from documents.utils import run_subprocess

    out_pattern = tempdir / "glm-ocr-page-%03d.png"
    run_subprocess(
        [
            "gs",
            "-q",
            "-dNOPAUSE",
            "-dBATCH",
            "-dSAFER",
            "-sDEVICE=png16m",
            f"-r{_RASTER_DPI}",
            f"-o{out_pattern}",
            str(document_path),
        ],
        logger=logger,
    )
    return sorted(tempdir.glob("glm-ocr-page-*.png"))
