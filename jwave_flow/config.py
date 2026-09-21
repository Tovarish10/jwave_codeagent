"""Environment-driven configuration (kept deliberately portable).

Everything that differs between machines lives here and is read from
environment variables / a local ``.env`` file, so the workflow can be moved to
another host without editing code.
"""
from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional dependency
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    def load_dotenv(*_args, **_kwargs):  # type: ignore
        return False

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_KB = PROJECT_ROOT / "kb" / "jwave_kb_organized.md"


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


@dataclass
class Settings:
    """All runtime knobs for the workflow."""

    # --- LLM (anything that speaks the OpenAI chat-completions API) ---
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    analyst_model: str = "deepseek-v4-flash"
    coder_model: str = "deepseek-v4-flash"
    temperature: float = 0.7
    request_timeout: float = 120.0
    max_retries: int = 2

    # --- Knowledge retrieval -------------------------------------------
    # "bm25"   -> pure-python lexical retrieval, no network, no extra deps
    # "openai" -> OpenAI-compatible embeddings + in-memory vector store
    kb_path: Path = field(default_factory=lambda: DEFAULT_KB)
    retrieval_backend: str = "bm25"
    top_k: int = 4
    embedding_model: str = "text-embedding-3-small"

    # --- Code execution ------------------------------------------------
    # "subprocess" (default) | "jupyter" | "mcp" | "auto"
    executor_backend: str = "subprocess"
    exec_python: str = sys.executable
    exec_timeout: float = 600.0
    # Defaults that keep generated simulation code *quiet on stderr*, because the
    # ⑦ 条件分支 node treats any stderr output as a failure:
    #   * JAX_PLATFORMS=cpu  -> the default CUDA backend segfaults on some hosts
    #   * MPLBACKEND=Agg     -> no GUI window when running headless
    #   * MPLCONFIGDIR       -> otherwise matplotlib prints a cache warning to stderr
    exec_env: dict[str, str] = field(
        default_factory=lambda: {
            "JAX_PLATFORMS": "cpu",
            "MPLBACKEND": "Agg",
            "MPLCONFIGDIR": os.path.join(tempfile.gettempdir(), "jwave-flow-mpl"),
        }
    )
    workdir: Path = field(default_factory=lambda: PROJECT_ROOT / "run")

    # --- Workflow -------------------------------------------------------
    max_iterations: int = 10          # mirrors Dify loop_count
    verbose: bool = True

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        load_dotenv(PROJECT_ROOT / ".env")
        load_dotenv()  # also honour a .env in the current directory
        kwargs: dict = dict(
            openai_api_key=_env("OPENAI_API_KEY") or _env("DEEPSEEK_API_KEY"),
            openai_base_url=_env("OPENAI_BASE_URL") or _env("DEEPSEEK_BASE_URL"),
            analyst_model=_env("ANALYST_MODEL", "deepseek-v4-flash"),
            coder_model=_env("CODER_MODEL", "deepseek-v4-flash"),
            temperature=float(_env("LLM_TEMPERATURE", "0.7")),
            request_timeout=float(_env("LLM_TIMEOUT", "120")),
            kb_path=Path(_env("KB_PATH", str(DEFAULT_KB))).expanduser(),
            retrieval_backend=_env("RETRIEVAL_BACKEND", "bm25"),
            top_k=int(_env("RETRIEVAL_TOP_K", "4")),
            embedding_model=_env("EMBEDDING_MODEL", "text-embedding-3-small"),
            executor_backend=_env("EXECUTOR_BACKEND", "subprocess"),
            exec_python=_env("EXEC_PYTHON", sys.executable),
            exec_timeout=float(_env("EXEC_TIMEOUT", "600")),
            workdir=Path(_env("WORKDIR", str(PROJECT_ROOT / "run"))).expanduser(),
            max_iterations=int(_env("LOOP_MAX_ITERATIONS", "10")),
            verbose=(_env("VERBOSE", "1") not in ("0", "false", "False")),
        )
        kwargs.update(overrides)
        return cls(**kwargs)

    def resolved_kb_path(self) -> Path:
        return self.kb_path if self.kb_path.is_absolute() else (PROJECT_ROOT / self.kb_path)
