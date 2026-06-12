from __future__ import annotations

import asyncio
import unittest
from collections import deque

from event_loop import AsyncTkBridge


class FakeRoot:
    def __init__(self) -> None:
        self.callbacks = deque()
        self.delays: list[int] = []
        self.quit_called = False

    def after(self, delay_ms: int, callback) -> None:
        self.delays.append(delay_ms)
        self.callbacks.append(callback)

    def mainloop(self) -> None:
        while self.callbacks and not self.quit_called:
            self.callbacks.popleft()()

    def quit(self) -> None:
        self.quit_called = True


class AsyncTkBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.loop = asyncio.new_event_loop()

    def tearDown(self) -> None:
        pending = asyncio.all_tasks(self.loop)
        for task in pending:
            task.cancel()
        if pending:
            self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self.loop.close()

    def test_runs_task_to_completion_and_quits_tk(self) -> None:
        async def application() -> int:
            await asyncio.sleep(0)
            return 7

        root = FakeRoot()
        task = self.loop.create_task(application())

        result = AsyncTkBridge(root, self.loop, task).run()

        self.assertEqual(result, 7)
        self.assertTrue(root.quit_called)
        self.assertEqual(root.delays[0], 0)
        self.assertIn(10, root.delays)

    def test_propagates_application_exception(self) -> None:
        async def application() -> int:
            raise ValueError("boom")

        root = FakeRoot()
        task = self.loop.create_task(application())

        with self.assertRaisesRegex(ValueError, "boom"):
            AsyncTkBridge(root, self.loop, task).run()

    def test_close_request_wakes_application_task(self) -> None:
        close_requested = asyncio.Event()

        async def application() -> int:
            await close_requested.wait()
            return 0

        root = FakeRoot()
        root.after(0, close_requested.set)
        task = self.loop.create_task(application())

        result = AsyncTkBridge(root, self.loop, task).run()

        self.assertEqual(result, 0)
        self.assertTrue(root.quit_called)

    def test_fails_if_tk_exits_while_task_is_pending(self) -> None:
        class EarlyExitRoot(FakeRoot):
            def mainloop(self) -> None:
                return

        async def application() -> int:
            await asyncio.Event().wait()
            return 0

        root = EarlyExitRoot()
        task = self.loop.create_task(application())

        with self.assertRaisesRegex(RuntimeError, "exited before"):
            AsyncTkBridge(root, self.loop, task).run()


if __name__ == "__main__":
    unittest.main()
