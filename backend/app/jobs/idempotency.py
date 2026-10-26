import hashlib
import json


def canonical_input_hash(value: dict) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def job_idempotency_key(project_id: str, action: str, input_hash: str) -> str:
    return canonical_input_hash({'project_id': project_id, 'action': action, 'input_hash': input_hash})
