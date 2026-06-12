from __future__ import annotations

import asyncio
from typing import Any, Protocol


class TkRoot(Protocol):
    def after(self, delay_ms: int, callback: Any) -> Any: ...

    def mainloop(self) -> None: ...

    def quit(self) -> None: ...


class AsyncTkBridge:
    """Run asyncio in short turns while Tk owns the native event loop."""

    def __init__(
        self,
        root: TkRoot,
        loop: asyncio.AbstractEventLoop,
        task: asyncio.Task[int],
        *,
        interval_ms: int = 10,
    ) -> None:
        self._root = root
        self._loop = loop
        self._task = task
        self._interval_ms = interval_ms
        self._stopped = False

    def run(self) -> int:
        self._root.after(0, self._pump)
        self._root.mainloop()
        if not self._task.done():
            raise RuntimeError("Tk main loop exited before the application task completed")
        return self._task.result()

    def _pump(self) -> None:
        if self._stopped:
            return
        self._loop.call_soon(self._loop.stop)
        self._loop.run_forever()
        if self._task.done():
            self._stopped = True
            self._root.quit()
            return
        self._root.after(self._interval_ms, self._pump)
