"""Voice transcription provider using LemonData API."""

import os
from pathlib import Path

import httpx
from loguru import logger


class TranscriptionProvider:
    """
    Voice transcription using LemonData's OpenAI-compatible endpoint.

    Uses the same API key and base URL as the chat provider,
    no extra configuration needed.
    """

    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        self.api_key = api_key or os.environ.get("API_KEY", "")
        base = api_base or os.environ.get("API_BASE_URL", "https://api.lemondata.cc/v1")
        self.api_url = f"{base.rstrip('/')}/audio/transcriptions"

    async def transcribe(self, file_path: str | Path) -> str:
        """Transcribe an audio file."""
        if not self.api_key:
            logger.warning("No API key configured for transcription")
            return ""

        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""

        try:
            async with httpx.AsyncClient() as client:
                with open(path, "rb") as f:
                    response = await client.post(
                        self.api_url,
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        files={"file": (path.name, f)},
                        data={"model": "whisper-large-v3"},
                        timeout=60.0,
                    )
                    response.raise_for_status()
                    return response.json().get("text", "")
        except Exception as e:
            logger.error("Transcription error: {}", e)
            return ""
