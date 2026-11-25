import asyncio
import sys
from collections.abc import Coroutine
from typing import Any


def run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        return asyncio.run(coroutine, loop_factory=asyncio.SelectorEventLoop)
    return asyncio.run(coroutine)
