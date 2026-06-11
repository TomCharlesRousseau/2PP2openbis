"""
openBIS connection handler for printjob2openbis.

Supports PAT (Personal Access Token) authentication with keyring caching
and password fallback, mirroring the uvsheet2openbis connection module.
"""

from getpass import getpass
from typing import Optional

from config.settings import Settings
from utils.logger import get_logger

logger = get_logger(__name__)

# Optional keyring import for secure credential storage.
try:
    import keyring

    _KEYRING_AVAILABLE = True
except ImportError:
    _KEYRING_AVAILABLE = False
    logger.warning("keyring not available. Install with: pip install keyring")


def _get_cached_pat(username: str) -> str:
    """
    Retrieve a cached PAT from the system keyring.

    Args:
        username: openBIS username.

    Returns:
        Cached PAT string, or empty string if not available.
    """
    if not _KEYRING_AVAILABLE:
        return ""
    try:
        pat = keyring.get_password("openbis", username)
        if pat:
            logger.debug(f"Retrieved cached PAT for {username}")
            return pat
        logger.info(f"No cached PAT found in keyring for {username}")
        return ""
    except Exception as exc:
        logger.warning(f"Error retrieving PAT from keyring: {exc}")
        return ""


def _cache_pat(username: str, pat: str) -> bool:
    """
    Store a PAT in the system keyring.

    Args:
        username: openBIS username.
        pat: Personal Access Token to cache.

    Returns:
        ``True`` if the PAT was cached successfully.
    """
    if not _KEYRING_AVAILABLE:
        return False
    try:
        keyring.set_password("openbis", username, pat)
        logger.debug(f"Cached PAT for {username}")
        return True
    except Exception as exc:
        logger.warning(f"Could not cache PAT: {exc}")
        return False


def _extract_pat(openbis) -> Optional[str]:
    """
    Extract the session token from a connected pybis instance.

    Args:
        openbis: Connected ``pybis.Openbis`` instance.

    Returns:
        Token string or ``None`` if unavailable.
    """
    try:
        if hasattr(openbis, "token") and openbis.token:
            return openbis.token
    except Exception as exc:
        logger.debug(f"Could not extract PAT: {exc}")
    return None


def get_openbis_connection():
    """
    Connect to openBIS using a PAT-first authentication strategy.

    Attempts, in order:
    1. Cached PAT from system keyring.
    2. Password login, then caches the resulting token.

    Returns:
        ``pybis.Openbis`` instance on success, ``None`` on failure.
    """
    try:
        from pybis import Openbis
    except ImportError as exc:
        logger.error(f"Required package missing: {exc}")
        logger.error("Install with: pip install pybis")
        return None

    cfg = Settings()
    url = cfg.openbis_url
    username = cfg.openbis_username

    if not username:
        logger.error("openBIS username not configured in config/settings.json")
        return None

    logger.info(f"Connecting to openBIS: {url}")
    logger.info(f"User: {username}")

    try:
        cached_pat = _get_cached_pat(username)
        if cached_pat:
            logger.info("Attempting login with cached PAT...")
            try:
                openbis = Openbis(url, token=cached_pat)
                logger.info("Successfully logged in with cached PAT")
                return openbis
            except Exception as exc:
                logger.debug(f"Cached PAT expired or invalid: {exc}")
                logger.info("Falling back to password authentication...")

        logger.info("Attempting login with password...")
        openbis = Openbis(url)
        password = getpass(f"Enter openBIS password for {username}: ")

        if not password:
            logger.error("No password provided")
            return None

        openbis.login(username, password)
        logger.info("Successfully logged in with password")

        pat = _extract_pat(openbis)
        if pat:
            if _cache_pat(username, pat):
                logger.info(f"PAT cached for {username} (will be used next time)")
            else:
                logger.warning("Failed to cache PAT")
        else:
            logger.warning("No PAT token available to cache")

        return openbis

    except Exception as exc:
        logger.error(f"Failed to connect to openBIS: {exc}")
        return None


class OpenBISConnection:
    """Manages the lifecycle of an openBIS connection."""

    def __init__(self) -> None:
        """Initialise an unconnected manager."""
        self.openbis = None

    def connect(self):
        """
        Establish (or reuse) a connection to openBIS.

        Returns:
            ``pybis.Openbis`` instance or ``None`` if connection failed.
        """
        if self.openbis is None:
            self.openbis = get_openbis_connection()
        return self.openbis

    def disconnect(self) -> None:
        """Log out and release the connection."""
        if self.openbis:
            try:
                self.openbis.logout()
                logger.info("Disconnected from openBIS")
            except Exception as exc:
                logger.warning(f"Error during logout: {exc}")
            self.openbis = None

    def is_connected(self) -> bool:
        """Return ``True`` if a connection is currently active."""
        return self.openbis is not None
