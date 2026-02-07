"""Video processor - extracts audio and key frames for processing."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Optional

import ffmpeg

from ingestion.metadata import ExtractedContent, SourceMetadata
from ingestion.processors.audio import AudioProcessor
from ingestion.processors.base import BaseProcessor
from ingestion.processors.image import ImageProcessor


class VideoProcessor(BaseProcessor):
    """Process video files by extracting audio and key frames."""

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        extract_audio: bool = True,
        extract_frames: bool = True,
        num_frames: int = 10,
        frame_strategy: str = "uniform",  # "uniform", "key_frames", "scene_change"
    ):
        """
        Initialize video processor.

        Args:
            openai_api_key: OpenAI API key
            extract_audio: Extract and transcribe audio track
            extract_frames: Extract and describe key frames
            num_frames: Number of frames to extract
            frame_strategy: Strategy for frame selection
        """
        self.extract_audio = extract_audio
        self.extract_frames = extract_frames
        self.num_frames = num_frames
        self.frame_strategy = frame_strategy

        if extract_audio:
            self.audio_processor = AudioProcessor(openai_api_key=openai_api_key)
        if extract_frames:
            self.image_processor = ImageProcessor(openai_api_key=openai_api_key)

    def can_process(self, content: ExtractedContent) -> bool:
        """Check if content is video."""
        return (
            content.metadata.source_type == "video"
            or content.metadata.original_format
            in (
                "mp4",
                "avi",
                "mov",
                "mkv",
                "webm",
            )
        )

    def process(self, content: ExtractedContent, **kwargs) -> ExtractedContent:
        """Process video to extract audio transcript and frame descriptions."""
        start_time = time.time()

        video_path = content.raw_content_path
        if not video_path or not video_path.exists():
            raise ValueError(f"Video file not found: {video_path}")

        # Get video metadata
        video_info = self._get_video_info(video_path)
        duration_seconds = video_info.get("duration", 0)

        parts = [f"# Video: {video_path.name}\n"]
        parts.append(f"Duration: {duration_seconds:.1f} seconds")
        parts.append(
            f"Resolution: {video_info.get('width', '?')}x{video_info.get('height', '?')}"
        )
        parts.append("")

        total_cost = 0.0

        # Extract and transcribe audio
        if self.extract_audio:
            try:
                audio_content = self._extract_audio(video_path, content.metadata)
                audio_content = self.audio_processor.process(audio_content)
                parts.append("## Audio Transcription\n")
                parts.append(audio_content.text)
                parts.append("")
                total_cost += audio_content.metadata.processing_cost_usd or 0.0
            except Exception as e:
                parts.append(f"## Audio Transcription\n[Failed: {e}]\n")

        # Extract and process frames
        if self.extract_frames:
            try:
                frame_descriptions = self._extract_and_process_frames(
                    video_path, duration_seconds, content.metadata
                )
                parts.append("## Visual Summary (Key Frames)\n")
                for i, desc in enumerate(frame_descriptions, 1):
                    parts.append(f"### Frame {i}\n{desc}\n")
                total_cost += self._estimate_frame_cost(len(frame_descriptions))
            except Exception as e:
                parts.append(f"## Visual Summary\n[Failed: {e}]\n")

        # Update metadata
        content.metadata.processing_steps.append("video_processing")
        content.metadata.processing_model = "whisper-1 + gpt-5.2"
        content.metadata.processing_cost_usd = total_cost
        content.metadata.processing_duration_seconds = time.time() - start_time
        content.metadata.custom_metadata["video_duration"] = duration_seconds
        content.metadata.custom_metadata["video_resolution"] = (
            f"{video_info.get('width', '?')}x{video_info.get('height', '?')}"
        )

        # Update text
        content.text = "\n".join(parts)

        return content

    def _get_video_info(self, video_path: Path) -> dict:
        """Get video metadata."""
        try:
            probe = ffmpeg.probe(str(video_path))
            video_stream = next(
                (s for s in probe["streams"] if s["codec_type"] == "video"), None
            )
            format_info = probe.get("format", {})

            return {
                "duration": float(format_info.get("duration", 0)),
                "width": int(video_stream.get("width", 0)) if video_stream else 0,
                "height": int(video_stream.get("height", 0)) if video_stream else 0,
                "fps": (
                    eval(video_stream.get("r_frame_rate", "0/1")) if video_stream else 0
                ),
            }
        except Exception:
            return {"duration": 0, "width": 0, "height": 0, "fps": 0}

    def _extract_audio(
        self, video_path: Path, parent_metadata: SourceMetadata
    ) -> ExtractedContent:
        """Extract audio track from video."""
        from ingestion.metadata import ExtractedContent, SourceMetadata

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_audio:
            audio_path = Path(tmp_audio.name)

        try:
            # Extract audio using ffmpeg
            stream = ffmpeg.input(str(video_path))
            stream = ffmpeg.output(
                stream, str(audio_path), acodec="pcm_s16le", ac=1, ar="16k"
            )
            ffmpeg.run(stream, overwrite_output=True, quiet=True)

            # Create ExtractedContent for audio
            metadata = SourceMetadata(
                source_type="audio",
                source_url=str(audio_path),
                source_id=f"{video_path.stem}_audio",
                ingested_at=parent_metadata.ingested_at,
                original_format="wav",
                mime_type="audio/wav",
                extraction_method="video_audio_extraction",
                parent_source_id=parent_metadata.source_id,
            )

            return ExtractedContent(
                text="",
                metadata=metadata,
                raw_content_path=audio_path,
            )
        except Exception as e:
            if audio_path.exists():
                audio_path.unlink()
            raise Exception(f"Audio extraction failed: {e}") from e

    def _extract_and_process_frames(
        self, video_path: Path, duration: float, parent_metadata: SourceMetadata
    ) -> list[str]:
        """Extract and process key frames."""
        from ingestion.metadata import ExtractedContent, SourceMetadata

        frame_paths = []

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Extract frames
            if self.frame_strategy == "uniform":
                # Uniform sampling
                interval = duration / (self.num_frames + 1)
                timestamps = [interval * (i + 1) for i in range(self.num_frames)]
            else:
                # Default to uniform
                interval = duration / (self.num_frames + 1)
                timestamps = [interval * (i + 1) for i in range(self.num_frames)]

            for i, timestamp in enumerate(timestamps):
                frame_path = tmp_path / f"frame_{i:04d}.png"
                try:
                    # Extract frame at timestamp
                    (
                        ffmpeg.input(str(video_path), ss=timestamp)
                        .output(str(frame_path), vframes=1)
                        .overwrite_output()
                        .run(quiet=True)
                    )
                    frame_paths.append(frame_path)
                except Exception:
                    continue

            # Process each frame
            descriptions = []
            for frame_path in frame_paths:
                if frame_path.exists():
                    try:
                        # Create temporary ExtractedContent for frame
                        frame_metadata = SourceMetadata(
                            source_type="image",
                            source_url=str(frame_path),
                            source_id=f"{video_path.stem}_frame_{frame_path.stem}",
                            ingested_at=parent_metadata.ingested_at,
                            original_format="png",
                            mime_type="image/png",
                            extraction_method="video_frame_extraction",
                            parent_source_id=parent_metadata.source_id,
                        )
                        frame_content = ExtractedContent(
                            text="",
                            metadata=frame_metadata,
                            raw_content_path=frame_path,
                        )

                        # Process frame
                        processed = self.image_processor.process(frame_content)
                        descriptions.append(processed.text)
                    except Exception as e:
                        descriptions.append(f"[Frame processing failed: {e}]")

        return descriptions

    def _estimate_frame_cost(self, num_frames: int) -> float:
        """Estimate cost for frame processing."""
        # GPT-4 Vision: ~$0.01-0.03 per image
        return num_frames * 0.02  # Average estimate
