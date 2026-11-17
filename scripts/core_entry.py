"""Entry point for the frozen desktop core.

PyInstaller needs a plain script as its entry point. Keeping it separate from
``app/desktop.py`` lets the package stay importable in a source checkout.
"""

from __future__ import annotations

from app.desktop import main

if __name__ == "__main__":
    main()
