"""Plugin-level configuration (ADR-0019)."""
from __future__ import annotations

import os

PLUGIN_VERSION: str = "0.3.0"

# Vercel proxy → Linear Feedback team. Override for staging / local testing.
FEEDBACK_PROXY_URL: str = os.environ.get(
    "REDICHECK_FEEDBACK_PROXY_URL",
    "https://redicheck-feedback.vercel.app/api/feedback",
)

SUBJECT_PREFIX = "[redicheck-ai]"
