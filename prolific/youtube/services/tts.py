"""Re-export from shared services for backward compatibility."""

from prolific.services.tts import TTSService, get_tts_service

__all__ = ["TTSService", "get_tts_service"]
