"""Drain authenticated and hosted requests before deleting their owner's files."""

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
import inspect

from starlette.responses import JSONResponse


@dataclass(eq=False)
class Activity:
    task: asyncio.Task
    request_scope: dict
    user_id: int | None = None
    stopping: bool = False
    done: asyncio.Event = field(default_factory=asyncio.Event)


_current: ContextVar[Activity | None] = ContextVar('user_activity', default=None)
_requests: set[Activity] = set()


def track_user_activity(user_id: int) -> None:
    # Sync handlers run in a copied context; the activity object is shared.
    if activity := _current.get():
        activity.user_id = user_id


async def cancel_user_requests(user_id: int) -> None:
    requests = [activity for activity in _requests if activity.user_id == user_id]
    for activity in requests:
        if not activity.stopping:
            activity.stopping = True
            # Cancel async work once so its async finalizers can drain processes.
            # Sync handlers must finish in their worker threads before files are removed.
            if inspect.iscoroutinefunction(activity.request_scope.get('endpoint')):
                activity.task.cancel()
    if requests:
        await asyncio.wait_for(asyncio.gather(*(activity.done.wait() for activity in requests)), timeout=30)


class UserActivityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        started = complete = False

        async def tracked_send(message):
            nonlocal started, complete
            await send(message)
            if message['type'] == 'http.response.start':
                started = True
            elif message['type'] == 'http.response.body' and not message.get('more_body', False):
                complete = True

        activity = Activity(asyncio.current_task(), scope)
        token = _current.set(activity)
        _requests.add(activity)
        try:
            await self.app(scope, receive, tracked_send)
        except asyncio.CancelledError:
            if not activity.stopping:
                raise
            if not started:
                await JSONResponse({'detail': 'This account is being deleted'}, status_code=401)(scope, receive, send)
            elif not complete:
                await send({'type': 'http.response.body', 'body': b'', 'more_body': False})
        finally:
            _current.reset(token)
            _requests.discard(activity)
            activity.done.set()
