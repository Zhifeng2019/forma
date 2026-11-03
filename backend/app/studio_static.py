"""Serve the studio's browser routes without turning missing APIs or assets into HTML."""

import re

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


STUDIO_ROUTES = re.compile(r'^(?:login|register|settings|admin|projects/[A-Za-z0-9_-]+)?/?$')


class StudioStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        if path.split('/', 1)[0] in {'api', 'apps', 'preview'}:
            raise HTTPException(404)
        if path == '.' or STUDIO_ROUTES.fullmatch(path):
            response = await super().get_response('index.html', scope)
            response.headers['Cache-Control'] = 'no-cache'
            return response
        return await super().get_response(path, scope)
