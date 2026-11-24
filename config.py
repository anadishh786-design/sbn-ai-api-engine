import os
from dataclasses import dataclass
from urllib.parse import urlparse


DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_API_TIMEOUT_SECONDS = 5.0


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class ClientConfig:
    base_url: str
    timeout_seconds: float


def validate_base_url(value):
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError("API base URL is missing.")

    candidate = value.strip().rstrip("/")
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ConfigurationError("API base URL must be a valid HTTP or HTTPS URL.")
    if parsed.username is not None or parsed.password is not None:
        raise ConfigurationError("API base URL must not contain credentials.")
    if parsed.query or parsed.fragment:
        raise ConfigurationError("API base URL must not contain a query or fragment.")
    return candidate


def validate_timeout(value):
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        raise ConfigurationError("API timeout must be a positive number.")
    if timeout <= 0:
        raise ConfigurationError("API timeout must be a positive number.")
    return timeout


def load_config(environ=None):
    environ = os.environ if environ is None else environ
    base_url = environ.get("API_BASE_URL", DEFAULT_API_BASE_URL)
    timeout_value = environ.get(
        "API_TIMEOUT_SECONDS",
        str(DEFAULT_API_TIMEOUT_SECONDS),
    )
    return ClientConfig(
        base_url=validate_base_url(base_url),
        timeout_seconds=validate_timeout(timeout_value),
    )
