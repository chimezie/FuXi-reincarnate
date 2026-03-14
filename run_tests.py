#!/usr/bin/env python
"""Pytest runner for fuxi."""

from __future__ import annotations

import sys

import pytest


def main() -> int:
    args = sys.argv[1:]
    if not args:
        args = ["-ra", "test"]
    return pytest.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
