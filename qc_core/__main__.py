"""``python -m qc_core`` dispatcher.

Mirrors the console scripts in pyproject.toml so the dev-mode invocation
documented in docs/agents/dev-mode.md actually works. Without this, ``python
-m qc_core.cli <subcommand>`` imported the module but ran nothing (no
``__main__`` guard), exiting 0 with no output.
"""

from __future__ import annotations

import sys

from qc_core.cli import main

if __name__ == "__main__":
    sys.exit(main())
