# -*- coding: utf-8 -*-
"""FuXi.LP - Backward compatibility shim for fuxi.LP."""

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
    _lp_module = importlib.import_module("fuxi.LP")
    __all__ = list(getattr(_lp_module, "__all__", []))
    for name in dir(_lp_module):
        if not name.startswith("_"):
            globals()[name] = getattr(_lp_module, name)
except ImportError as e:
    __all__ = []
    raise ImportError("FuXi.LP shim failed. Original error: {}".format(e))
_warn_once()
