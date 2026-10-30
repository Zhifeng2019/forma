import asyncio
import json
import re
import httpx
from .jobs.context import current_job_context
from .jobs.models import JobCancelledError
from .jobs.usage import record_observed_completion
from .security import decrypt_secret


class GenerationError(RuntimeError):
    pass


def _escape_json_control_characters(text: str) -> str:
    """Escape literal control characters inside JSON strings without changing other content."""
    output = []
    in_string = False
    escaped = False
    for character in text:
        if escaped:
            output.append(character)
            escaped = False
            continue
        if character == '\\':
            output.append(character)
            escaped = True
            continue
        if character == '"':
            in_string = not in_string
            output.append(character)
            continue
        if in_string and ord(character) < 0x20:
            escapes = {'\n': '\\n', '\r': '\\r', '\t': '\\t'}
            output.append(escapes.get(character, f'\\u{ord(character):04x}'))
        else:
            output.append(character)
    return ''.join(output)


def _json_loads(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        sanitized = _escape_json_control_characters(text)
        if sanitized == text:
            raise
        return json.loads(sanitized)


def parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text)
    try:
        value = _json_loads(text)
    except json.JSONDecodeError as exc:
        start, end = text.find('{'), text.rfind('}')
        if start < 0 or end <= start:
            raise GenerationError('The model did not return a valid structured result.') from exc
        try:
            value = _json_loads(text[start:end + 1])
        except json.JSONDecodeError as inner:
            raise GenerationError('The model response could not be parsed. Please retry.') from inner
    if not isinstance(value, dict):
        raise GenerationError('The model response must be a JSON object.')
    return value


MAX_OUTPUT_TOKENS = 32_768
OUTPUT_REPAIR_ATTEMPTS = 1


def _inference_options(provider: dict) -> dict:
    """Keep deterministic coding output separate from model reasoning."""
    name = provider['name'].strip().lower()
    model = provider['model'].strip().lower()
    if 'moonshot' in name and model == 'kimi-k3':
        return {'reasoning_effort': 'low'}
    if 'deepseek' in name:
        return {'thinking': {'type': 'disabled'}}
    return {}


async def complete(provider: dict, system: str, prompt: str) -> dict:
    return await _complete(provider, system, prompt, {'type': 'json_object'})


async def complete_with_schema(
    provider: dict, system: str, prompt: str, schema: dict, schema_name: str,
) -> dict:
    """Use native structured output when available, with one compatibility fallback."""
    response_format = {
        'type': 'json_schema',
        'json_schema': {'name': schema_name, 'strict': True, 'schema': schema},
    }
    return await _complete(provider, system, prompt, response_format, allow_json_fallback=True)


async def _post_with_cancellation(client, url, kwargs, tool_metadata=None):
    context = current_job_context()
    if context:
        context.raise_if_cancelled()
    run = None
    if tool_metadata:
        from .jobs.tool_runs import start_tool_run, finish_tool_run
        run = start_tool_run(
            'provider.http', 'openai-compatible.chat-completions.v1', tool_metadata['input'],
            retry_count=tool_metadata['retry_count'], provenance=tool_metadata['provenance'],
        )
    request = asyncio.create_task(client.post(url, **kwargs))
    cancellation_waiter = asyncio.create_task(context.cancellation.wait()) if context else None
    try:
        if cancellation_waiter:
            done, _ = await asyncio.wait(
                {request, cancellation_waiter}, return_when=asyncio.FIRST_COMPLETED,
            )
            if cancellation_waiter in done:
                request.cancel()
                await asyncio.gather(request, return_exceptions=True)
                context.raise_if_cancelled()
        response = await request
        if context:
            context.raise_if_cancelled()
        finished = None
        if run:
            succeeded = response.status_code < 400
            finished = finish_tool_run(
                run, 'succeeded' if succeeded else 'failed',
                provenance={'http_status': response.status_code},
                error=None if succeeded else f'Provider HTTP {response.status_code}',
            )
        return response, finished
    except (JobCancelledError, asyncio.CancelledError) as exc:
        if run:
            finish_tool_run(run, 'cancelled', error=f'{type(exc).__name__}: {exc}')
        raise
    except Exception as exc:
        if run:
            finish_tool_run(run, 'failed', error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        if cancellation_waiter:
            cancellation_waiter.cancel()


async def _complete(
    provider: dict, system: str, prompt: str, response_format: dict,
    allow_json_fallback: bool = False,
) -> dict:
    if not provider:
        raise GenerationError('Choose a model provider in Configuration, or use the local engine.')
    if not provider.get('api_key_encrypted'):
        raise GenerationError(f'{provider["name"]} has no API key configured.')
    url = provider['base_url'].rstrip('/') + '/chat/completions'
    messages = [
        {'role': 'system', 'content': system + '\nReturn only one valid JSON object.'},
        {'role': 'user', 'content': prompt},
    ]
    try:
        # Provider egress is explicit: malformed host-level NO_PROXY values must
        # not prevent the OpenAI-compatible client from initializing.
        async with httpx.AsyncClient(timeout=240, trust_env=False) as client:
            attempt = 0
            request_sequence = 0
            request_reason = 'initial'
            reason_detail = None
            continuation = False
            continuation_source = ''
            while attempt <= OUTPUT_REPAIR_ATTEMPTS:
                response, tool_run = await _post_with_cancellation(client, url, {
                    'headers': {'Authorization': f'Bearer {decrypt_secret(provider["api_key_encrypted"])}'},
                    'json': {'model': provider['model'], 'messages': messages,
                             'temperature': 0.35, 'response_format': response_format,
                             'max_tokens': MAX_OUTPUT_TOKENS, **_inference_options(provider)},
                }, tool_metadata={
                    'input': {
                        'provider': provider['name'], 'model': provider['model'],
                        'response_format': response_format,
                    },
                    'retry_count': request_sequence,
                    'provenance': {
                        'provider': provider['name'], 'model': provider['model'],
                        'response_format_type': response_format.get('type'),
                        'schema_name': response_format.get('json_schema', {}).get('name'),
                    },
                })
                record_observed_completion(
                    provider, response, tool_run, response_format=response_format,
                    request_reason=request_reason, reason_detail=reason_detail, retry_count=request_sequence,
                )
                request_sequence += 1
                if response.status_code >= 400:
                    if (allow_json_fallback and response_format.get('type') == 'json_schema'
                            and response.status_code in {400, 404, 422}):
                        response_format = {'type': 'json_object'}
                        request_reason = 'schema_fallback'
                        reason_detail = f'HTTP {response.status_code}'
                        continue
                    raise GenerationError(f'Provider returned {response.status_code}: {response.text[:300]}')
                payload = response.json()
                choices = payload.get('choices') or []
                if not choices:
                    raise GenerationError('The provider returned an empty response.')
                choice = choices[0]
                fragment = str(choice.get('message', {}).get('content') or '').strip()
                content = continuation_source + fragment if continuation else fragment
                finish_reason = str(choice.get('finish_reason') or '')
                if finish_reason != 'length':
                    try:
                        if continuation:
                            try:
                                if current_job_context():
                                    current_job_context().raise_if_cancelled()
                                return parse_json(fragment)
                            except GenerationError:
                                pass
                        if current_job_context():
                            current_job_context().raise_if_cancelled()
                        return parse_json(content)
                    except GenerationError:
                        if attempt >= OUTPUT_REPAIR_ATTEMPTS:
                            raise
                elif attempt >= OUTPUT_REPAIR_ATTEMPTS:
                    raise GenerationError(
                        f'The model reached the {MAX_OUTPUT_TOKENS:,}-token output limit twice. '
                        'Try splitting the application into a smaller first phase.'
                    )
                if finish_reason == 'length':
                    reason = 'truncated by the output token limit'
                    continuation_source = content
                    messages = [
                        *messages,
                        {'role': 'assistant', 'content': content},
                        {'role': 'user', 'content': (
                            'The previous response stopped because it reached the output token limit. '
                            'Continue exactly from its final character. Output only the remaining text; '
                            'do not repeat or restart the JSON, and do not add commentary or Markdown fences.'
                        )},
                    ]
                    request_reason = 'output_continuation'
                    continuation = True
                else:
                    reason = 'invalid JSON'
                    messages = [
                        *messages,
                        {'role': 'assistant', 'content': content[:64_000]},
                        {'role': 'user', 'content': (
                            'The previous response was invalid JSON. Return the complete result again '
                            'as one valid JSON object. Keep the implementation concise enough to fit '
                            'the output budget. Do not add commentary or Markdown fences.'
                        )},
                    ]
                    request_reason = 'output_repair'
                    continuation = False
                    continuation_source = ''
                reason_detail = reason
                attempt += 1
        raise GenerationError('The model did not return a usable structured response.')
    except JobCancelledError:
        raise
    except GenerationError:
        raise
    except Exception as exc:
        raise GenerationError(f'Unable to reach {provider["name"]}: {str(exc)[:220]}') from exc
