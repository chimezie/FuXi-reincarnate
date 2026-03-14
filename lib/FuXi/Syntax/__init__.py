# -*- coding: utf-8 -*-
"""FuXi.Syntax - Backward compatibility shim for fuxi.Syntax."""

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
    _syntax_module = importlib.import_module("fuxi.Syntax")
    __all__ = list(getattr(_syntax_module, "__all__", []))
    for name in dir(_syntax_module):
        if not name.startswith("_"):
            globals()[name] = getattr(_syntax_module, name)
except ImportError as e:
    __all__ = []
    raise ImportError("FuXi.Syntax shim failed. Original error: {}".format(e))
_warn_once()
