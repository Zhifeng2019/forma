"""Browser-test entrypoint. Fake delivery exists only in this test module.

Production launches app.main:app and cannot enable this mailbox via settings.
The real verification, expiry, rate limits, and admin approval routes stay active.
"""
import json
import os
from pathlib import Path

from app.authentication import delivery
from app.config import settings
from app.main import app  # noqa: F401


def capture(channel, destination, code, challenge_id, *, purpose='registration'):
    root = settings.data_path / 'test-deliveries'
    root.mkdir(exist_ok=True)
    path = root / f'{challenge_id}.json'
    pending = path.with_suffix('.tmp')
    pending.write_text(json.dumps({'channel': channel, 'destination': destination, 'code': code, 'purpose': purpose}))
    os.chmod(pending, 0o600)
    pending.replace(path)


# Require a separate, explicit test database before installing the test adapter.
if not os.environ.get('FORMA_TEST_DATA_DIR') or settings.data_path != Path(os.environ['FORMA_TEST_DATA_DIR']).resolve():
    raise RuntimeError('Browser tests require their own FORMA_TEST_DATA_DIR')
delivery.send_verification = capture
delivery.configuration_status = lambda purpose='registration': {
    channel: {'enabled': True, 'configured': True, 'available': True} for channel in ('email', 'sms')
}
