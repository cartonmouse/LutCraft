import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
os.environ.setdefault("VIPS_CONCURRENCY", "2")


@dataclass
class Settings:
    data: Path
    secret: str
    model_url: str = ""
    model_name: str = ""
    model_key: str = ""
    timeout: float = 30
    max_bytes: int = 10 * 1024 * 1024
    max_pixels: int = 24_000_000
    max_assets: int = 10
    queue_limit: int = 20

    agent_runtime: str = "manual"
    openclaw_url: str = ""
    openclaw_token: str = ""
    openclaw_agent: str = "lut-color"
    openclaw_version: str = ""
    openclaw_verified: bool = False
    bridge_token: str = ""
    agent_timeout: float = 90
    agent_tool_limit: int = 12
    model_provider: str = "compatible"
    embedding_provider: str = "disabled"
    embedding_url: str = ""
    embedding_model: str = ""
    embedding_version: str = "1"
    embedding_key: str = ""
    embedding_dimensions: int = 1024
    embedding_send_dimensions: bool = True
    embedding_timeout: float = 10
    embedding_batch_size: int = 10
    embedding_query_prefix: str = ""
    embedding_document_prefix: str = ""
    embedding_min_similarity: float | None = None

    @property
    def openclaw_configured(self):
        return bool(
            self.openclaw_url
            and self.openclaw_token
            and self.bridge_token
            and self.openclaw_agent
            and self.openclaw_version
        )

    def __post_init__(self):
        self.data = self.data.resolve()
        if self.embedding_provider not in ("disabled", "compatible"):
            raise ValueError("EMBEDDING_PROVIDER must be disabled or compatible")
        if not 1 <= self.embedding_dimensions <= 8192 or not 1 <= self.embedding_batch_size <= 100:
            raise ValueError("Invalid embedding dimensions/batch size")
        if not 1 <= self.embedding_timeout <= 60:
            raise ValueError("Invalid embedding timeout")
        if self.embedding_min_similarity is not None and not -1 <= self.embedding_min_similarity <= 1:
            raise ValueError("Invalid embedding similarity threshold")
        if self.embedding_url:
            from urllib.parse import urlparse
            url = urlparse(self.embedding_url)
            if (url.scheme not in ("http", "https") or not url.hostname or url.username or url.password
                    or url.fragment or url.query or
                    (url.scheme == "http" and url.hostname not in ("localhost", "127.0.0.1", "::1"))):
                raise ValueError("Embedding URL requires HTTPS (or local HTTP), without credentials")
        if self.model_provider not in ("compatible", "deepseek"):
            raise ValueError("MODEL_PROVIDER must be compatible or deepseek")
        if self.agent_runtime not in ("manual", "direct", "openclaw"):
            raise ValueError("AGENT_RUNTIME must be manual, direct or openclaw")
        if not 1 <= self.agent_timeout <= 600 or not 1 <= self.agent_tool_limit <= 50:
            raise ValueError("Invalid Agent limits")
        if self.openclaw_url:
            from urllib.parse import urlparse

            url = urlparse(self.openclaw_url)
            if (
                url.scheme not in ("http", "https")
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
                or url.path not in ("", "/")
            ):
                raise ValueError("OPENCLAW_GATEWAY_URL must be a server origin")
            if url.scheme == "http" and url.hostname not in (
                "localhost",
                "127.0.0.1",
                "::1",
            ):
                raise ValueError("Remote Gateway requires HTTPS")

    @property
    def model_configured(self):
        return bool(self.model_url and self.model_name and self.model_key)

    @classmethod
    def load(cls):
        p = Path(os.getenv("DATA_DIR", str(ROOT / "data"))).resolve()
        p.mkdir(parents=True, exist_ok=True)
        secret_path = p / ".session-secret"
        if not secret_path.exists():
            secret_path.write_text(secrets.token_urlsafe(48))
            secret_path.chmod(0o600)
        return cls(
            p,
            os.getenv("SESSION_SECRET") or secret_path.read_text().strip(),
            os.getenv("MODEL_API_URL", ""),
            os.getenv("MODEL_NAME", ""),
            os.getenv("MODEL_API_KEY", ""),
            float(os.getenv("MODEL_TIMEOUT", "30")),
            agent_runtime=os.getenv("AGENT_RUNTIME", "manual"),
            openclaw_url=os.getenv("OPENCLAW_GATEWAY_URL", ""),
            openclaw_token=os.getenv("OPENCLAW_GATEWAY_TOKEN", ""),
            openclaw_agent=os.getenv("OPENCLAW_AGENT_ID", "lut-color"),
            openclaw_version=os.getenv("OPENCLAW_VERIFIED_VERSION", ""),
            openclaw_verified=os.getenv(
                "OPENCLAW_COMPATIBILITY_VERIFIED", "false"
            ).lower()
            == "true",
            bridge_token=os.getenv("OPENCLAW_BRIDGE_TOKEN", ""),
            agent_timeout=float(os.getenv("AGENT_TIMEOUT", "90")),
            agent_tool_limit=int(os.getenv("AGENT_TOOL_LIMIT", "12")),
            model_provider=os.getenv("MODEL_PROVIDER", "compatible"),
            embedding_provider=os.getenv("EMBEDDING_PROVIDER", "disabled"),
            embedding_url=os.getenv("EMBEDDING_API_URL", ""),
            embedding_model=os.getenv("EMBEDDING_MODEL", ""),
            embedding_version=os.getenv("EMBEDDING_VERSION", "1"),
            embedding_key=os.getenv("EMBEDDING_API_KEY", ""),
            embedding_dimensions=int(os.getenv("EMBEDDING_DIMENSIONS", "1024")),
            embedding_send_dimensions=os.getenv("EMBEDDING_SEND_DIMENSIONS", "true").lower() == "true",
            embedding_timeout=float(os.getenv("EMBEDDING_TIMEOUT", "10")),
            embedding_batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE", "10")),
            embedding_query_prefix=os.getenv("EMBEDDING_QUERY_PREFIX", ""),
            embedding_document_prefix=os.getenv("EMBEDDING_DOCUMENT_PREFIX", ""),
            embedding_min_similarity=float(os.environ["EMBEDDING_MIN_SIMILARITY"]) if os.getenv("EMBEDDING_MIN_SIMILARITY") else None,
        )
