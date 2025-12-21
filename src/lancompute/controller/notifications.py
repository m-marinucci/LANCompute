"""Gotify notification integration for LANCompute Controller."""

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class GotifyNotifier:
    """Send notifications via Gotify push notification server."""

    def __init__(
        self,
        url: Optional[str] = None,
        token: Optional[str] = None,
        timeout: int = 10,
    ):
        """Initialize Gotify notifier.

        Parameters can be provided directly or via environment variables:
        - GOTIFY_URL
        - GOTIFY_TOKEN
        """
        self.url = url or os.environ.get("GOTIFY_URL", "http://192.168.1.134:30215")
        self.token = token or os.environ.get("GOTIFY_TOKEN", "")
        self.timeout = timeout
        self._enabled = bool(self.token)

        if not self._enabled:
            logger.warning("Gotify token not configured - notifications disabled")

    def send(
        self,
        title: str,
        message: str,
        priority: int = 5,
    ) -> bool:
        """Send a notification.

        Args:
            title: Notification title
            message: Notification body
            priority: 0-10, higher is more important (default 5)

        Returns:
            True if notification was sent successfully
        """
        if not self._enabled:
            logger.debug(f"Notification skipped (disabled): {title}")
            return False

        try:
            response = requests.post(
                f"{self.url}/message",
                params={"token": self.token},
                data={
                    "title": title,
                    "message": message,
                    "priority": priority,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            logger.info(f"Notification sent: {title}")
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to send notification: {e}")
            return False

    def job_submitted(self, job_name: str, job_id: str) -> bool:
        """Notify that a job was submitted."""
        return self.send(
            title="Job Submitted",
            message=f"Job '{job_name}' submitted (ID: {job_id[:8]}...)",
            priority=3,
        )

    def job_started(self, job_name: str, worker_id: str) -> bool:
        """Notify that a job started running."""
        return self.send(
            title="Job Started",
            message=f"Job '{job_name}' is now running on {worker_id}",
            priority=4,
        )

    def job_completed(self, job_name: str, duration_seconds: Optional[float] = None) -> bool:
        """Notify that a job completed successfully."""
        duration_str = ""
        if duration_seconds is not None:
            if duration_seconds < 60:
                duration_str = f" ({duration_seconds:.1f}s)"
            elif duration_seconds < 3600:
                duration_str = f" ({duration_seconds/60:.1f}m)"
            else:
                duration_str = f" ({duration_seconds/3600:.1f}h)"

        return self.send(
            title="Job Completed",
            message=f"Job '{job_name}' completed successfully{duration_str}",
            priority=5,
        )

    def job_failed(self, job_name: str, error: Optional[str] = None) -> bool:
        """Notify that a job failed."""
        message = f"Job '{job_name}' failed"
        if error:
            # Truncate long error messages
            if len(error) > 200:
                error = error[:197] + "..."
            message += f": {error}"

        return self.send(
            title="Job Failed",
            message=message,
            priority=8,
        )

    def worker_online(self, worker_id: str, hostname: str) -> bool:
        """Notify that a worker came online."""
        return self.send(
            title="Worker Online",
            message=f"Worker '{worker_id}' ({hostname}) is now online",
            priority=3,
        )

    def worker_offline(self, worker_id: str, hostname: str) -> bool:
        """Notify that a worker went offline."""
        return self.send(
            title="Worker Offline",
            message=f"Worker '{worker_id}' ({hostname}) went offline",
            priority=7,
        )
