from __future__ import annotations

from typing import Callable

from locallens.core.config import Settings
from locallens.core.types import ExtractionStats, IndexedUnit, ScannedFile
from locallens.extractors.image_extractor import ImageExtractor
from locallens.extractors.pdf_extractor import PdfExtractor
from locallens.extractors.pdf_ocr_table_cache import PdfOcrTableReadThroughCache
from locallens.extractors.text_extractor import TextExtractor


class ExtractorRouter:
    def __init__(
        self,
        settings: Settings,
        pdf_ocr_table_cache: PdfOcrTableReadThroughCache | None = None,
    ):
        self.text = TextExtractor(settings)
        self.pdf = PdfExtractor(settings, ocr_table_cache=pdf_ocr_table_cache)
        self.image = ImageExtractor(settings)
        self.last_stats = ExtractionStats()

    def extract(
        self,
        scanned: ScannedFile,
        progress_callback: Callable[[str, int, int], object] | None = None,
    ) -> list[IndexedUnit]:
        self.last_stats = ExtractionStats()
        if scanned.file_type == "text":
            return self.text.extract(scanned)
        if scanned.file_type == "pdf":
            try:
                return self.pdf.extract(scanned, progress_callback=progress_callback)
            finally:
                self.last_stats = self.pdf.last_stats
        if scanned.file_type == "image":
            return self.image.extract(scanned)
        return []
