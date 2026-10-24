"""任务事件总线：把引擎产生的事件分发给订阅了该任务的 WebSocket 连接。"""

from __future__ import annotations

import asyncio


class EventBus:
    """按 task_id 分发事件；没有订阅者时直接丢弃，不落盘也不阻塞。"""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}

    def subscribe(self, task_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.setdefault(task_id, set()).add(queue)
        return queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue) -> None:
        queues = self._subscribers.get(task_id)
        if not queues:
            return
        queues.discard(queue)
        if not queues:
            self._subscribers.pop(task_id, None)

    def publish(self, message: dict) -> None:
        """引擎可能从事件循环外调用，因此这里绝不阻塞。"""
        queues = self._subscribers.get(message.get("task_id", ""), set())
        for queue in list(queues):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # 订阅端处理不过来时丢弃最旧的一条，保证界面持续有新事件
                try:
                    queue.get_nowait()
                    queue.put_nowait(message)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass
