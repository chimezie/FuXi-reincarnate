# -*- coding: utf-8 -*-
"""
FuXi - Backward compatibility shim for fuxi package.

WARNING: The 'FuXi' module name is deprecated and will be removed in a future version.
Please use 'fuxi' (lowercase) instead:

    import fuxi
    from fuxi.Rete.Network import ReteNetwork

This shim exists only to maintain backward compatibility with existing code.
"""

import importlib
import warnings

# Emit deprecation warning once per module load
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


# Import fuxi and re-export everything for backward compatibility
try:
    import fuxi as _fuxi_module

    __all__ = list(getattr(_fuxi_module, "__all__", []))

    Rete = importlib.import_module("fuxi.Rete")
    Horn = importlib.import_module("fuxi.Horn")
    DLP = importlib.import_module("fuxi.DLP")
    LP = importlib.import_module("fuxi.LP")
    SPARQL = importlib.import_module("fuxi.SPARQL")
    Syntax = importlib.import_module("fuxi.Syntax")

    for name, module in (
        ("Rete", Rete),
        ("Horn", Horn),
        ("DLP", DLP),
        ("LP", LP),
        ("SPARQL", SPARQL),
        ("Syntax", Syntax),
    ):
        globals()[name] = module
        if name not in __all__:
            __all__.append(name)

except ImportError as e:
    __all__ = []
    Rete = Horn = DLP = LP = SPARQL = Syntax = None
    raise ImportError(
        "FuXi shim failed to import fuxi package. "
        "Make sure the canonical 'fuxi' package is installed. "
        "Original error: {}".format(e)
    )

# Trigger warning on first use
_warn_once()
