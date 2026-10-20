"""
Network utilities with retry logic and connection pooling.
Fixes timeout and reliability issues.
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Optional
from constants import NetworkConfig
from logger import get_logger

logger = get_logger(__name__)

# Module-level session (singleton pattern)
_session: Optional[requests.Session] = None


def get_session() -> requests.Session:
    """
    Get a requests session with connection pooling and retry logic.

    Returns:
        requests.Session: Configured session instance

    Example:
        >>> session = get_session()
        >>> response = session.get("https://example.com", timeout=30)
    """
    global _session

    if _session is None:
        _session = create_session_with_retries()

    return _session


def create_session_with_retries(
    total_retries: int = NetworkConfig.MAX_RETRIES,
    backoff_factor: float = NetworkConfig.BACKOFF_FACTOR,
    status_forcelist: tuple = (429, 500, 502, 503, 504)
) -> requests.Session:
    """
    Create a requests session with retry strategy and connection pooling.

    Args:
        total_retries: Maximum number of retry attempts
        backoff_factor: Exponential backoff multiplier
        status_forcelist: HTTP status codes to retry on

    Returns:
        requests.Session: Configured session

    Example:
        >>> session = create_session_with_retries()
        >>> response = session.get(url, timeout=30)
    """
    session = requests.Session()

    # Configure retry strategy
    retry_strategy = Retry(
        total=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=["GET", "POST", "PUT", "DELETE", "HEAD"]
    )

    # Configure connection pooling
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=NetworkConfig.POOL_CONNECTIONS,
        pool_maxsize=NetworkConfig.POOL_MAXSIZE
    )

    session.mount("http://", adapter)
    session.mount("https://", adapter)

    logger.debug(f"Created session with {total_retries} retries and connection pooling")

    return session


def download_with_size_limit(
    url: str,
    max_size: int,
    timeout: int = NetworkConfig.DEFAULT_TIMEOUT,
    chunk_size: int = NetworkConfig.CHUNK_SIZE
) -> bytes:
    """
    Download content with size limit to prevent memory exhaustion.

    Args:
        url: URL to download
        max_size: Maximum size in bytes
        timeout: Request timeout in seconds
        chunk_size: Size of chunks to download

    Returns:
        bytes: Downloaded content

    Raises:
        ValueError: If content exceeds max_size
        requests.RequestException: If download fails

    Example:
        >>> content = download_with_size_limit(
        ...     "https://example.com/image.jpg",
        ...     max_size=10*1024*1024  # 10MB
        ... )
    """
    session = get_session()

    try:
        response = session.get(url, stream=True, timeout=timeout)
        response.raise_for_status()

        # Check Content-Length header if available
        content_length = response.headers.get('Content-Length')
        if content_length:
            content_length = int(content_length)
            if content_length > max_size:
                raise ValueError(
                    f"Content too large: {content_length} bytes "
                    f"(max: {max_size} bytes)"
                )

        # Stream download with size limit
        chunks = []
        total_size = 0

        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:  # filter out keep-alive chunks
                total_size += len(chunk)
                if total_size > max_size:
                    raise ValueError(
                        f"Content exceeds {max_size} bytes during download"
                    )
                chunks.append(chunk)

        content = b''.join(chunks)
        logger.debug(f"Downloaded {total_size} bytes from {url}")
        return content

    except requests.RequestException as e:
        logger.error(f"Failed to download {url}: {e}")
        raise


def close_session():
    """Close the global session. Useful for cleanup."""
    global _session
    if _session:
        _session.close()
        _session = None
        logger.debug("Closed global session")
