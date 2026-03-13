"""Re-export from shared services for backward compatibility."""

from prolific.services.image_gen import ImageGenService, get_image_gen_service

__all__ = ["ImageGenService", "get_image_gen_service"]
