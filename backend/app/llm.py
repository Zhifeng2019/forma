import json
import re
import httpx
from .security import decrypt_secret


class GenerationError(RuntimeError):
    pass


def parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        start, end = text.find('{'), text.rfind('}')
        if start < 0 or end <= start:
            raise GenerationError('The model did not return a valid structured result.') from exc
        try:
            value = json.loads(text[start:end + 1])
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
            while attempt <= OUTPUT_REPAIR_ATTEMPTS:
                response = await client.post(url,
                    headers={'Authorization': f'Bearer {decrypt_secret(provider["api_key_encrypted"])}'},
                    json={'model': provider['model'], 'messages': messages,
                          'temperature': 0.35, 'response_format': response_format,
                          'max_tokens': MAX_OUTPUT_TOKENS, **_inference_options(provider)})
                if response.status_code >= 400:
                    if (allow_json_fallback and response_format.get('type') == 'json_schema'
                            and response.status_code in {400, 404, 422}):
                        response_format = {'type': 'json_object'}
                        continue
                    raise GenerationError(f'Provider returned {response.status_code}: {response.text[:300]}')
                payload = response.json()
                choices = payload.get('choices') or []
                if not choices:
                    raise GenerationError('The provider returned an empty response.')
                choice = choices[0]
                content = str(choice.get('message', {}).get('content') or '').strip()
                finish_reason = str(choice.get('finish_reason') or '')
                if finish_reason != 'length':
                    try:
                        return parse_json(content)
                    except GenerationError:
                        if attempt >= OUTPUT_REPAIR_ATTEMPTS:
                            raise
                elif attempt >= OUTPUT_REPAIR_ATTEMPTS:
                    raise GenerationError(
                        f'The model reached the {MAX_OUTPUT_TOKENS:,}-token output limit twice. '
                        'Try splitting the application into a smaller first phase.'
                    )
                reason = 'truncated by the output token limit' if finish_reason == 'length' else 'invalid JSON'
                messages = [
                    *messages,
                    {'role': 'assistant', 'content': content[:64_000]},
                    {'role': 'user', 'content': (
                        f'The previous response was {reason}. Return the complete result again '
                        'as one valid JSON object. Keep the implementation concise enough to fit '
                        'the output budget. Do not add commentary or Markdown fences.'
                    )},
                ]
                attempt += 1
        raise GenerationError('The model did not return a usable structured response.')
    except GenerationError:
        raise
    except Exception as exc:
        raise GenerationError(f'Unable to reach {provider["name"]}: {str(exc)[:220]}') from exc
