# -*- coding: utf-8 -*-
"""
FuXi.Rete - Backward compatibility shim for fuxi.Rete.

WARNING: The 'FuXi' module name is deprecated and will be removed in a future version.
Please use 'fuxi.Rete' instead.
"""

import importlib
import warnings

_warnings_emitted = False


def _warn_once():
    global _warnings_emitted
    if not _warnings_emitted:
        warnings.warn(
            "FuXi is deprecated and will be removed in a future version. "
            "Please use 'fuxi' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        _warnings_emitted = True


try:
    _rete_module = importlib.import_module("fuxi.Rete")

    __all__ = list(getattr(_rete_module, "__all__", []))

    # Re-export everything from fuxi.Rete
    for name in dir(_rete_module):
        if not name.startswith("_"):
            globals()[name] = getattr(_rete_module, name)

except ImportError as e:
    __all__ = []
    raise ImportError(
        "FuXi.Rete shim failed to import fuxi.Rete. Original error: {}".format(e)
    )

_warn_once()
