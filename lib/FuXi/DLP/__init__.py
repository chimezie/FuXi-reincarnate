# -*- coding: utf-8 -*-
"""FuXi.DLP - Backward compatibility shim for fuxi.DLP."""

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
    _dlp_module = importlib.import_module("fuxi.DLP")
    __all__ = list(getattr(_dlp_module, "__all__", []))
    for name in dir(_dlp_module):
        if not name.startswith("_"):
            globals()[name] = getattr(_dlp_module, name)
except ImportError as e:
    __all__ = []
    raise ImportError("FuXi.DLP shim failed. Original error: {}".format(e))
_warn_once()
