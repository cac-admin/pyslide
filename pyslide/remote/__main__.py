# -*- coding: utf-8 -*-
""" Entry point for ``python -m pyslide.remote``."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
