"""Image processor using GPT-4 Vision and OCR."""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Optional

from openai import OpenAI
from PIL import Image

from ingestion.metadata import ExtractedContent
from ingestion.processors.base import BaseProcessor


class ImageProcessor(BaseProcessor):
    """Process images to extract text and descriptions."""

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        model: str = "gpt-5.2",
        use_ocr_fallback: bool = True,
        max_image_size_mb: float = 20.0,
    ):
        """
        Initialize image processor.

        Args:
            openai_api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: Model to use ("gpt-5.2", "gpt-4-vision-preview")
            use_ocr_fallback: Use pytesseract for simple text extraction
            max_image_size_mb: Maximum image size in MB
        """
        self.client = OpenAI(api_key=openai_api_key or os.environ.get("OPENAI_API_KEY"))
        self.model = model
        self.use_ocr_fallback = use_ocr_fallback
        self.max_image_size_mb = max_image_size_mb

        if use_ocr_fallback:
            try:
                import pytesseract

                self.pytesseract = pytesseract
            except ImportError:
                self.use_ocr_fallback = False

    def can_process(self, content: ExtractedContent) -> bool:
        """Check if content is an image."""
        return (
            content.metadata.source_type == "image"
            or content.metadata.original_format
            in (
                "png",
                "jpg",
                "jpeg",
                "gif",
                "webp",
            )
        )

    def process(self, content: ExtractedContent, **kwargs) -> ExtractedContent:
        """Process image to extract text and description."""
        start_time = time.time()

        image_path = content.raw_content_path
        if not image_path or not image_path.exists():
            raise ValueError(f"Image file not found: {image_path}")

        # Check image size
        size_mb = image_path.stat().st_size / (1024 * 1024)
        if size_mb > self.max_image_size_mb:
            raise ValueError(
                f"Image too large: {size_mb:.2f}MB (max: {self.max_image_size_mb}MB)"
            )

        # Process with GPT-4 Vision
        try:
            description = self._process_with_gpt4_vision(image_path)
            processing_model = self.model
            cost_estimate = self._estimate_cost(image_path)
        except Exception as e:
            # Fallback to OCR if GPT-4 fails
            if self.use_ocr_fallback:
                description = self._process_with_ocr(image_path)
                processing_model = "pytesseract"
                cost_estimate = 0.0
            else:
                raise Exception(f"Image processing failed: {e}") from e

        duration = time.time() - start_time

        # Update metadata
        content.metadata.processing_steps.append("image_processing")
        content.metadata.processing_model = processing_model
        content.metadata.processing_cost_usd = cost_estimate
        content.metadata.processing_duration_seconds = duration

        # Add description to additional_texts
        content.additional_texts["image_description"] = description

        # If original text is just metadata, replace it
        if not content.text or content.text.startswith("[Image:"):
            content.text = f"# Image: {image_path.name}\n\n{description}"

        return content

    def _process_with_gpt4_vision(self, image_path: Path) -> str:
        """Process image using GPT-4 Vision."""
        # Read and encode image
        with open(image_path, "rb") as image_file:
            image_data = base64.b64encode(image_file.read()).decode("utf-8")

        # Determine image format
        img = Image.open(image_path)
        mime_type = f"image/{img.format.lower()}" if img.format else "image/png"

        # Call GPT-4 Vision
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Extract all text from this image using OCR, and describe the key visual elements. "
                                "Format the output as markdown. If there's text, include it verbatim. "
                                "If there are diagrams, charts, or visual elements, describe them clearly."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_data}",
                            },
                        },
                    ],
                }
            ],
            max_tokens=1000,
        )

        return response.choices[0].message.content

    def _process_with_ocr(self, image_path: Path) -> str:
        """Process image using OCR (fallback)."""
        if not self.use_ocr_fallback:
            raise ValueError("OCR fallback not available")

        try:
            text = self.pytesseract.image_to_string(Image.open(image_path))
            return f"# Extracted Text (OCR)\n\n{text}"
        except Exception as e:
            return f"[OCR failed: {e}]"

    def _estimate_cost(self, image_path: Path) -> float:
        """Estimate API cost for image processing."""
        # GPT-4 Vision pricing (approximate)
        # Low detail: $0.0025 per image
        # High detail: $0.01-0.03 per image
        # We use high detail for better quality
        size_mb = image_path.stat().st_size / (1024 * 1024)
        if size_mb < 0.5:
            return 0.01  # Small image
        elif size_mb < 2.0:
            return 0.02  # Medium image
        else:
            return 0.03  # Large image
