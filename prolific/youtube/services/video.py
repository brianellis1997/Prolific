"""Re-export from shared services for backward compatibility."""

from prolific.services.video import VideoAssemblyService, get_video_assembly_service

__all__ = ["VideoAssemblyService", "get_video_assembly_service"]
