"""Route untrusted application content exclusively to dedicated browser origins."""

import hashlib
import re
from urllib.parse import urlsplit

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from .config import settings


def studio_origins() -> set[str]:
    return {settings.studio_base_url, *settings.cors_origins.split(',')}


def application_origin(project_id: str, version: int | None = None) -> str:
    base = urlsplit(settings.apps_base_url)
    # Hashes also support historical IDs that are not valid DNS labels.
    label = hashlib.sha256(project_id.encode()).hexdigest()[:32]
    label = f'preview-{label}-v{version}' if version is not None else f'app-{label}'
    port = f':{base.port}' if base.port else ''
    return f'{base.scheme}://{label}.{base.hostname}{port}'


def published_url(project_id: str) -> str:
    return f'{application_origin(project_id)}/apps/{project_id}/'


def preview_url(project_id: str, version: int, token: str) -> str:
    return f'{application_origin(project_id, version)}/preview/{project_id}/{version}/{token}/'


class ApplicationOriginMiddleware:
    """Enforce the host boundary before either the API router or SPA can run.

    The reverse proxy must preserve Host. No forwarded host supplied by a client
    participates in the decision. Unknown hosts fail closed.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        host = request.url.netloc.lower()
        studio_hosts = {urlsplit(origin).netloc.lower() for origin in studio_origins()}
        public = re.fullmatch(r'/apps/([^/]+)(?:/.*)?', request.url.path)
        preview = re.fullmatch(r'/preview/([^/]+)/([1-9][0-9]{0,8})/([^/]+)(?:/.*)?', request.url.path)
        expected = (application_origin(public[1]) if public else
                    application_origin(preview[1], int(preview[2])) if preview else None)
        generated = expected is not None and host == urlsplit(expected).netloc.lower()
        if not generated:
            if host not in studio_hosts:
                await JSONResponse({'detail': 'This host does not serve this resource'}, status_code=404)(scope, receive, send)
                return
            if public:
                if request.method not in ('GET', 'HEAD'):
                    await JSONResponse({'detail': 'Use the published application URL'}, status_code=404)(scope, receive, send)
                    return
                target = expected + request.url.path
                if request.url.query:
                    target += '?' + request.url.query
                await RedirectResponse(target, status_code=307, headers={'Referrer-Policy': 'no-referrer'})(scope, receive, send)
                return
            if preview:
                await JSONResponse({'detail': 'Use the isolated preview URL'}, status_code=404)(scope, receive, send)
                return

        async def isolated_send(message):
            if message['type'] == 'http.response.start':
                headers = MutableHeaders(scope=message)
                headers['Origin-Agent-Cluster'] = '?1'
                headers['X-Content-Type-Options'] = 'nosniff'
                headers['Referrer-Policy'] = 'no-referrer'
                if generated:
                    headers['Cache-Control'] = 'no-store'
                if generated and preview:
                    headers['Content-Security-Policy'] = 'frame-ancestors ' + ' '.join(sorted(studio_origins()))
                elif not generated:
                    headers['Cross-Origin-Opener-Policy'] = 'same-origin'
            await send(message)

        await self.app(scope, receive, isolated_send)
