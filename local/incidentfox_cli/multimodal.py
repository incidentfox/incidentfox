"""
Multimodal input support for IncidentFox CLI.

Provides:
- Image detection and encoding (drag & drop / file paths)
- Voice recording and transcription
"""

import base64
import io
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

# Image extensions we support
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

# Audio extensions for reference (used by voice recording)
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}


def is_image_path(text: str) -> Optional[Path]:
    """
    Check if text looks like an image file path.

    When users drag files into the terminal, most terminals paste the file path.
    This detects if the input is a path to an image file.

    Args:
        text: User input text

    Returns:
        Path object if it's a valid image path, None otherwise
    """
    text = text.strip()

    # Remove quotes that some terminals add
    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        text = text[1:-1]

    # Handle escaped spaces (drag-drop on some terminals)
    text = text.replace("\\ ", " ")

    # Check if it looks like a path
    if not text:
        return None

    path = Path(text).expanduser()

    # Check extension
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        return None

    # Check if file exists
    if not path.exists():
        return None

    return path


def encode_image_base64(image_path: Path) -> tuple[str, str]:
    """
    Read and base64 encode an image file.

    Args:
        image_path: Path to the image file

    Returns:
        Tuple of (base64_data, media_type)
    """
    # Determine media type
    ext = image_path.suffix.lower()
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    media_type = media_types.get(ext, "image/png")

    # Read and encode
    with open(image_path, "rb") as f:
        data = f.read()

    base64_data = base64.b64encode(data).decode("utf-8")
    return base64_data, media_type


def build_image_message(image_path: Path, prompt: str = "") -> str:
    """
    Build a message with embedded image for the agent.

    Since the current API is text-only, we encode the image in a special format
    that can be parsed by the agent to construct a multimodal message.

    The format uses XML-like tags that the agent can parse:
    <image src="data:image/png;base64,..." />

    Args:
        image_path: Path to the image
        prompt: Optional text prompt to accompany the image

    Returns:
        Formatted message string with embedded image
    """
    base64_data, media_type = encode_image_base64(image_path)

    # Build the message with image data URL
    image_tag = f'<image src="data:{media_type};base64,{base64_data}" />'

    if prompt:
        return f"{prompt}\n\n{image_tag}"
    else:
        return f"Please analyze this image:\n\n{image_tag}"


def get_image_size(image_path: Path) -> tuple[int, int]:
    """Get image dimensions without heavy dependencies."""
    # Try to get size from file header
    with open(image_path, "rb") as f:
        header = f.read(32)

    # PNG
    if header[:8] == b"\x89PNG\r\n\x1a\n":
        w = int.from_bytes(header[16:20], "big")
        h = int.from_bytes(header[20:24], "big")
        return w, h

    # JPEG
    if header[:2] == b"\xff\xd8":
        f = open(image_path, "rb")
        try:
            f.seek(2)
            while True:
                marker = f.read(2)
                if len(marker) < 2:
                    break
                if marker[0] != 0xFF:
                    break
                if marker[1] in (0xC0, 0xC1, 0xC2):
                    f.read(3)  # length + precision
                    h = int.from_bytes(f.read(2), "big")
                    w = int.from_bytes(f.read(2), "big")
                    return w, h
                else:
                    length = int.from_bytes(f.read(2), "big")
                    f.seek(length - 2, 1)
        finally:
            f.close()

    return 0, 0  # Unknown


class VoiceRecorder:
    """
    Voice recording and transcription using OpenAI Whisper.

    Usage:
        recorder = VoiceRecorder()
        if recorder.is_available():
            text = await recorder.record_and_transcribe()
    """

    def __init__(self):
        self._sounddevice = None
        self._soundfile = None
        self._openai = None
        self._available = None
        self._sample_rate = 16000  # Whisper optimal sample rate

    def is_available(self) -> bool:
        """Check if voice recording is available."""
        if self._available is not None:
            return self._available

        try:
            import sounddevice
            import soundfile

            self._sounddevice = sounddevice
            self._soundfile = soundfile

            # Check OpenAI
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                self._available = False
                return False

            import openai

            self._openai = openai
            self._available = True
            return True

        except ImportError:
            self._available = False
            return False

    def get_missing_deps(self) -> list[str]:
        """Get list of missing dependencies."""
        missing = []
        try:
            import sounddevice
        except ImportError:
            missing.append("sounddevice")
        try:
            import soundfile
        except ImportError:
            missing.append("soundfile")
        try:
            import openai
        except ImportError:
            missing.append("openai")
        return missing

    async def record_and_transcribe(
        self,
        duration: float = 10.0,
        on_start: callable = None,
        on_stop: callable = None,
    ) -> Optional[str]:
        """
        Record audio and transcribe using OpenAI Whisper.

        Args:
            duration: Maximum recording duration in seconds
            on_start: Callback when recording starts
            on_stop: Callback when recording stops

        Returns:
            Transcribed text or None if failed
        """
        if not self.is_available():
            return None

        import asyncio

        # Record audio
        if on_start:
            on_start()

        try:
            # Record with sounddevice
            recording = self._sounddevice.rec(
                int(duration * self._sample_rate),
                samplerate=self._sample_rate,
                channels=1,
                dtype="float32",
            )

            # Wait for recording or early stop
            self._sounddevice.wait()

        except Exception as e:
            if on_stop:
                on_stop()
            raise RuntimeError(f"Recording failed: {e}")

        if on_stop:
            on_stop()

        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name

        try:
            self._soundfile.write(temp_path, recording, self._sample_rate)

            # Transcribe with Whisper
            client = self._openai.OpenAI()

            with open(temp_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="text",
                )

            return transcript.strip() if transcript else None

        finally:
            # Clean up
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def record_with_keypress(
        self,
        max_duration: float = 30.0,
    ) -> Optional[bytes]:
        """
        Record audio until user presses Enter.

        Returns raw audio bytes for processing.
        """
        if not self.is_available():
            return None

        import queue
        import threading

        audio_chunks = []
        stop_event = threading.Event()

        def audio_callback(indata, frames, time, status):
            if not stop_event.is_set():
                audio_chunks.append(indata.copy())

        # Start recording in background
        stream = self._sounddevice.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="float32",
            callback=audio_callback,
        )

        with stream:
            # Wait for stop signal (Enter key in calling code)
            stop_event.wait(timeout=max_duration)

        if not audio_chunks:
            return None

        # Combine chunks
        import numpy as np

        audio_data = np.concatenate(audio_chunks)

        return audio_data

    async def transcribe_audio(self, audio_data) -> Optional[str]:
        """
        Transcribe audio data using Whisper.

        Args:
            audio_data: numpy array of audio samples

        Returns:
            Transcribed text
        """
        if not self.is_available():
            return None

        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name

        try:
            self._soundfile.write(temp_path, audio_data, self._sample_rate)

            # Transcribe
            client = self._openai.OpenAI()

            with open(temp_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="text",
                )

            return transcript.strip() if transcript else None

        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


# Singleton recorder instance
_voice_recorder: Optional[VoiceRecorder] = None


def get_voice_recorder() -> VoiceRecorder:
    """Get the singleton voice recorder instance."""
    global _voice_recorder
    if _voice_recorder is None:
        _voice_recorder = VoiceRecorder()
    return _voice_recorder
