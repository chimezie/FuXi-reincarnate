# -*- coding: utf-8 -*-
"""FuXi.Horn - Backward compatibility shim for fuxi.Horn."""

import importlib
import warnings

_warnings_emitted = False


def _warn_once():
    global _warnings_emitted
    if not _warnings_emitted:
        warnings.warn(
            "FuXi is deprecated. Use 'fuxi' instead.", DeprecationWarning, stacklevel=2
        )
        _warnings_emitted = True


try:
    _horn_module = importlib.import_module("fuxi.Horn")
    __all__ = list(getattr(_horn_module, "__all__", []))
    for name in dir(_horn_module):
        if not name.startswith("_"):
            globals()[name] = getattr(_horn_module, name)
except ImportError as e:
    __all__ = []
    raise ImportError("FuXi.Horn shim failed. Original error: {}".format(e))
_warn_once()
