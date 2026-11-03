"""Forward application credentials only on the application's isolated host."""

import re


APPLICATION_REQUEST_HEADERS = frozenset({
    'accept', 'authorization', 'cookie', 'x-csrf-token', 'x-csrftoken', 'x-xsrf-token',
})
COOKIE_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")


def application_cookie(value: str, *, preview: bool, https: bool) -> str | None:
    """Scope cookies to this app host, with partitioned sessions for embedded previews.

    Each project/version already has a dedicated host. Path=/ deliberately avoids
    binding sessions to the short-lived preview grant in the URL. Keep separate
    Set-Cookie fields and opaque values, including quoted/escaped values and newer
    attributes that Python's cookie parser may not yet recognize.
    """
    if any(ord(char) < 32 and char != '\t' or ord(char) == 127 for char in value):
        return None
    parts, start, quoted, escaped = [], 0, False, False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
        elif quoted and char == '\\':
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif char == ';' and not quoted:
            parts.append(value[start:index].strip())
            start = index + 1
    if quoted:
        return None
    parts.append(value[start:].strip())
    name, separator, _value = parts[0].partition('=')
    if not separator or not COOKIE_NAME.fullmatch(name):
        return None
    removed = {'domain', 'path'}
    if preview:
        removed.update({'samesite', 'partitioned'})
    if preview or https:
        removed.add('secure')
    attributes = [part for part in parts[1:] if part and part.split('=', 1)[0].strip().lower() not in removed]
    attributes.append('Path=/')
    if preview or https:
        attributes.append('Secure')
    if preview:
        # Cross-site iframe sessions without granting access to other top-level sites.
        attributes.extend(['SameSite=None', 'Partitioned'])
    return '; '.join([parts[0], *attributes])
