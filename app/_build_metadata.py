"""Optional release-time stamps baked into wheels or sdists.

``scripts/embed_build_metadata`` overwrites this file before packaging so
``bunnify --version`` and the web UI still report a commit when ``.git`` is
absent (for example after ``pipx install`` from PyPI). Empty strings mean
"unset" and :mod:`app.version` falls back to env, then ``git``, then
``unknown``.
"""

from __future__ import annotations

EMBEDDED_COMMIT: str = ""
EMBEDDED_VERSION: str = ""
