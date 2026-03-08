"""SSOT defaults for LemonClaw configuration.

All default models, providers, STT settings, and LemonData-specific constants
are defined here. Other modules MUST import from this file instead of
hardcoding values.

Historical lesson: OpenClaw had STT provider names scattered across multiple deployment bootstraps and installers — the same bug appeared repeatedly.
"""

# ---------------------------------------------------------------------------
# LemonData API
# ---------------------------------------------------------------------------

LEMONDATA_API_BASE = "https://api.lemondata.cc"
LEMONDATA_API_BASE_V1 = f"{LEMONDATA_API_BASE}/v1"

# ---------------------------------------------------------------------------
# Default models
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_VISION_MODEL = "gpt-4.1-mini"
DEFAULT_FAST_MODEL = "gpt-4.1-mini"
DEFAULT_CONSOLIDATION_MODEL = "llama-3.3-70b-versatile"  # Groq: fast + cheap + good tool calling

# ---------------------------------------------------------------------------
# STT (Speech-to-Text)
# ---------------------------------------------------------------------------

DEFAULT_STT_MODEL = "whisper-large-v3"
DEFAULT_STT_PROVIDER = "lemondata"  # Uses openai-compatible endpoint

# ---------------------------------------------------------------------------
# Gateway defaults
# ---------------------------------------------------------------------------

DEFAULT_GATEWAY_PORT = 18789  # Matches OpenClaw for K8s probe compatibility
DEFAULT_GATEWAY_BIND = "localhost"  # Fail-closed: only localhost by default

# ---------------------------------------------------------------------------
# LemonData provider names (used in config and registry)
# ---------------------------------------------------------------------------

PROVIDER_LEMONDATA = "lemondata"
PROVIDER_LEMONDATA_CLAUDE = "lemondata_claude"
PROVIDER_LEMONDATA_MINIMAX = "lemondata_minimax"
PROVIDER_LEMONDATA_GEMINI = "lemondata_gemini"
