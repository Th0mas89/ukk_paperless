"""
Built-in GLM-OCR document parser.

Uses a local vision-capable LLM served by Ollama (default model "glm-4v")
to transcribe the text of scanned documents, instead of Tesseract.

Archive PDF generation, thumbnailing, page counting, date detection and
metadata extraction are all delegated unchanged to the Tesseract parser
(``RasterisedDocumentParser``) -- reimplementing that machinery for a
model that only outputs plain text would add a lot of new, untested surface
area for no benefit. Only the extracted text (``get_text()``) is replaced
with the GLM-OCR result.

If the GLM-OCR call fails for any reason (Ollama unreachable, timeout,
model not loaded, unexpected response, endpoint validation failure), the
Tesseract-extracted text is used instead and the failure is logged --
consumption never fails because this parser is configured.

When no valid GLM-OCR engine is configured, ``score()`` returns ``None``
so the parser is invisible to the registry and Tesseract handles these
MIME types as usual.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Self

from django.conf import settings

from paperless.parsers.tesseract import RasterisedDocumentParser
from paperless.version import __full_version_str__

if TYPE_CHECKING:
    import datetime
    from types import TracebackType

    from paperless.parsers import MetadataEntry
    from paperless.parsers import ParserContext

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


class GlmOcrDocumentParser:
    """Parse documents via a local vision LLM (GLM-OCR, served by Ollama).

    Class attributes
    ----------------
    name : str
        Human-readable parser name.
    version : str
        Semantic version string, kept in sync with Paperless-ngx releases.
    author : str
        Maintainer name.
    url : str
        Issue tracker / source URL.
    uses_remote_service : bool
        False -- the model runs on a locally-managed Ollama instance, not
        a third-party cloud service, so this parser is not gated by the
        ``allow_remote`` flag the way the Azure remote parser is.
    """

    name: str = "Paperless-ngx GLM-OCR Parser"
    version: str = __full_version_str__
    author: str = "Paperless-ngx Contributors"
    url: str = "https://github.com/paperless-ngx/paperless-ngx"

    uses_remote_service: bool = False

    # ------------------------------------------------------------------
    # Class methods
    # ------------------------------------------------------------------

    @classmethod
    def supported_mime_types(cls) -> dict[str, str]:
        return RasterisedDocumentParser.supported_mime_types()

    @classmethod
    def score(
        cls,
        mime_type: str,
        filename: str,
        path: Path | None = None,
    ) -> int | None:
        """Return the priority score for handling this file, or None.

        Returns ``None`` when GLM-OCR is not configured, making the parser
        invisible to the registry for this file. When configured, returns
        15 -- higher than Tesseract's 10 so GLM-OCR takes priority, but
        lower than a configured remote engine's 20.
        """
        config = GlmOcrConfig()
        if not config.is_valid():
            return None
        if mime_type not in cls.supported_mime_types():
            return None
        return 15

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def can_produce_archive(self) -> bool:
        return self._tesseract.can_produce_archive

    @property
    def requires_pdf_rendition(self) -> bool:
        return self._tesseract.requires_pdf_rendition

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __init__(self, logging_group: object | None = None) -> None:
        self._logging_group = logging_group
        # Tesseract stays responsible for the archive PDF, thumbnail, page
        # count, date and metadata -- and its own text serves as the
        # fallback if the GLM-OCR call fails.
        self._tesseract = RasterisedDocumentParser(logging_group)
        self._text: str | None = None
        self.used_fallback: bool = False

    def __enter__(self) -> Self:
        self._tesseract.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self._tesseract.__exit__(exc_type, exc_val, exc_tb)

    # ------------------------------------------------------------------
    # Core parsing interface
    # ------------------------------------------------------------------

    def configure(self, context: ParserContext) -> None:
        self._tesseract.configure(context)

    def parse(
        self,
        document_path: Path,
        mime_type: str,
        *,
        produce_archive: bool = True,
    ) -> None:
        self._tesseract.parse(document_path, mime_type, produce_archive=produce_archive)

        try:
            self._text = self._glm_ocr_parse(document_path, mime_type)
            self.used_fallback = False
        except Exception:
            logger.warning(
                "GLM-OCR failed for %s, falling back to Tesseract text",
                document_path,
                exc_info=True,
            )
            self._text = self._tesseract.get_text()
            self.used_fallback = True

    # ------------------------------------------------------------------
    # Result accessors -- all but text are delegated to Tesseract
    # ------------------------------------------------------------------

    def get_text(self) -> str:
        return self._text or ""

    def get_date(self) -> datetime.datetime | None:
        return self._tesseract.get_date()

    def get_archive_path(self) -> Path | None:
        return self._tesseract.get_archive_path()

    def get_thumbnail(self, document_path: Path, mime_type: str) -> Path:
        return self._tesseract.get_thumbnail(document_path, mime_type)

    def get_page_count(
        self,
        document_path: Path,
        mime_type: str,
    ) -> int | None:
        return self._tesseract.get_page_count(document_path, mime_type)

    def extract_metadata(
        self,
        document_path: Path,
        mime_type: str,
    ) -> list[MetadataEntry]:
        return self._tesseract.extract_metadata(document_path, mime_type)

    # ------------------------------------------------------------------
    # GLM-OCR
    # ------------------------------------------------------------------

    def _glm_ocr_parse(self, document_path: Path, mime_type: str) -> str:
        """Send each page of *document_path* to the GLM-OCR model and return the text.

        Raises
        ------
        Exception
            Any failure (invalid config, blocked endpoint, rasterisation
            failure, Ollama/network error) propagates to the caller, which
            treats it as "GLM-OCR unavailable" and falls back to Tesseract.
        """
        config = GlmOcrConfig()
        if not config.is_valid():
            raise RuntimeError("GLM-OCR is not configured")

        from paperless.network import validate_outbound_http_url

        validate_outbound_http_url(
            config.endpoint,
            allow_internal=config.allow_internal_endpoints,
        )

        images = self._render_pages(document_path, mime_type)
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

    def _render_pages(self, document_path: Path, mime_type: str) -> list[Path]:
        """Rasterise *document_path* to one PNG per page for the vision model.

        Non-PDF inputs are already images and are returned as a single-item
        list unchanged. Uses Ghostscript directly (already a dependency via
        ocrmypdf) rather than adding a new rasterisation library.
        """
        if mime_type != "application/pdf":
            return [document_path]

        from documents.utils import run_subprocess

        tempdir = self._tesseract.tempdir
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
