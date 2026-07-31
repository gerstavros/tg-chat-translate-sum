#!/usr/bin/env python3
"""Entry point for the standalone executable. Imports the real main from the package."""
import sys
import os

# εντοπισμός φακέλου package
pkg_dir = os.path.join(os.path.dirname(__file__), "package", "src")
if os.path.isdir(pkg_dir):
    sys.path.insert(0, pkg_dir)

from tg_translate.gui import main

if __name__ == "__main__":
    main()
