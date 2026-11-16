"""
Import a heavy library on first use instead of at start-up.

    pd = lazy_module("pandas")      # nothing is imported yet
    pd.DataFrame(...)               # the first attribute access imports pandas

Serverless instances start often (after idle time), and every request on a fresh instance waits
for the imports. pandas alone takes seconds, but only uploads need it, so the dataset modules
use this instead of `import pandas as pd`. Combine with `from __future__ import annotations`
so type hints like `pd.DataFrame` are not evaluated when the module loads.
"""

import importlib
from types import ModuleType
from typing import Any


class _LazyModule(ModuleType):
    def __init__(self, name: str):
        super().__init__(name)
        self._name = name
        self._module: ModuleType | None = None

    def __getattr__(self, attr: str) -> Any:
        if self._module is None:
            self._module = importlib.import_module(self._name)
        return getattr(self._module, attr)


def lazy_module(name: str) -> Any:
    return _LazyModule(name)
