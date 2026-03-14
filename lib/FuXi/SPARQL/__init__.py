# -*- coding: utf-8 -*-
"""FuXi.SPARQL - Backward compatibility shim for fuxi.SPARQL."""

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
    _sparql_module = importlib.import_module("fuxi.SPARQL")
    __all__ = list(getattr(_sparql_module, "__all__", []))
    for name in dir(_sparql_module):
        if not name.startswith("_"):
            globals()[name] = getattr(_sparql_module, name)
except ImportError as e:
    __all__ = []
    raise ImportError("FuXi.SPARQL shim failed. Original error: {}".format(e))
_warn_once()
