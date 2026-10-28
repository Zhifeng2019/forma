"""Observed model completions with explicit token and cost availability."""

from dataclasses import dataclass
import json

from ..database import workspace_db
from .redaction import redact_metadata, redact_output
from .tool_runs import ToolRunEnvelope


@dataclass(frozen=True)
class CompletionObservation:
    provider: str
    model: str
    provider_request_id: str | None
    finish_reason: str | None
    latency_ms: int
    usage_status: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cost_status: str
    estimated_cost: float | None
    currency: str | None
    input_price_per_million: float | None
    output_price_per_million: float | None
    metadata: dict


def _token(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _price(provider: dict, name: str) -> float | None:
    value = provider.get(name)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


def record_observed_completion(
    provider: dict,
    response,
    tool_run: ToolRunEnvelope | None,
    *,
    response_format: dict,
    request_reason: str,
    reason_detail: str | None,
    retry_count: int,
) -> CompletionObservation:
    """Capture provider-reported usage without inventing missing tokens or prices."""
    try:
        payload = response.json()
    except (ValueError, TypeError, AttributeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    usage = payload.get('usage') if isinstance(payload.get('usage'), dict) else {}
    input_tokens = _token(usage.get('prompt_tokens', usage.get('input_tokens')))
    output_tokens = _token(usage.get('completion_tokens', usage.get('output_tokens')))
    total_tokens = _token(usage.get('total_tokens'))
    observed = (input_tokens, output_tokens, total_tokens)
    usage_status = 'unavailable' if all(value is None for value in observed) else (
        'reported' if all(value is not None for value in observed) else 'partial'
    )
    input_price = _price(provider, 'input_price_per_million')
    output_price = _price(provider, 'output_price_per_million')
    estimated = None
    if input_tokens is not None and output_tokens is not None and input_price is not None and output_price is not None:
        estimated = round(
            input_tokens * input_price / 1_000_000 + output_tokens * output_price / 1_000_000,
            12,
        )
    cost_status = 'estimated' if estimated is not None else 'unknown'
    headers = getattr(response, 'headers', {}) or {}
    request_id = payload.get('id') or payload.get('request_id') or headers.get('x-request-id')
    choices = payload.get('choices') if isinstance(payload.get('choices'), list) else []
    first_choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    finish_reason = first_choice.get('finish_reason')
    currency = str(provider['currency']).upper() if provider.get('currency') else None
    metadata = redact_metadata({
        'request_reason': request_reason,
        'reason_detail': reason_detail,
        'retry_count': retry_count,
        'response_format_type': response_format.get('type'),
        'schema_name': response_format.get('json_schema', {}).get('name'),
        'observed_tokens': {'input': input_tokens, 'output': output_tokens, 'total': total_tokens},
        'estimated_cost': estimated,
        'cost_basis': 'provider_snapshot_prices' if estimated is not None else 'unavailable',
    })
    observation = CompletionObservation(
        provider=str(provider['name']), model=str(provider['model']),
        provider_request_id=redact_output(str(request_id))[:200] if request_id else None,
        finish_reason=redact_output(str(finish_reason))[:100] if finish_reason else None,
        latency_ms=tool_run.duration_ms if tool_run else 0,
        usage_status=usage_status, input_tokens=input_tokens, output_tokens=output_tokens,
        total_tokens=total_tokens, cost_status=cost_status, estimated_cost=estimated,
        currency=currency, input_price_per_million=input_price, output_price_per_million=output_price,
        metadata=metadata,
    )
    if tool_run:
        with workspace_db(tool_run.user_id) as db:
            db.execute('''INSERT INTO usage_ledger(
                job_id,tool_run_id,provider,model,input_tokens,output_tokens,estimated_cost,latency_ms,metadata,
                usage_status,cost_status,total_tokens,provider_request_id,finish_reason,
                input_price_per_million,output_price_per_million,currency)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
                tool_run.job_id, tool_run.id, observation.provider, observation.model,
                input_tokens or 0, output_tokens or 0, estimated if estimated is not None else 0,
                observation.latency_ms, json.dumps(metadata, sort_keys=True), usage_status, cost_status,
                total_tokens, observation.provider_request_id, observation.finish_reason,
                input_price, output_price, currency,
            ))
    return observation
