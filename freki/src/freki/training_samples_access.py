from __future__ import annotations


def is_training_samples_permission_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "training_samples" in message and "permission denied" in message
