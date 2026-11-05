"""Verification code delivery via SMTP and Aliyun SMS for mainland China.

No plaintext transport, automatic SMS retries, or logging of codes, recipients,
signed request URLs, provider response bodies, or credential-bearing exceptions.
"""
import asyncio
import hashlib
import hmac
import json
import re
import secrets
import smtplib
import ssl
from datetime import datetime, timezone
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate
from urllib.parse import quote, urlencode

import httpx
from pydantic import EmailStr, TypeAdapter

from ..config import settings


class DeliveryError(Exception):
    """A sanitized failure safe to expose to the registration layer."""


def _sms_template(purpose: str) -> str:
    if purpose == 'password_reset' and settings.aliyun_sms_password_reset_template_code:
        return settings.aliyun_sms_password_reset_template_code
    return settings.aliyun_sms_registration_template_code


def configuration_status(purpose: str = 'registration') -> dict:
    try:
        TypeAdapter(EmailStr).validate_python(settings.smtp_from_address)
        email_configured = bool(
            settings.smtp_host.strip() and settings.smtp_tls_mode in {'ssl', 'starttls'}
            and (not settings.smtp_username or settings.smtp_password)
            and len(settings.smtp_from_name) <= 128
            and not any(c in settings.smtp_from_name for c in '\r\n\x00')
        )
    except ValueError:
        email_configured = False
    sms_configured = bool(
        re.fullmatch(r'[A-Za-z0-9_-]{1,128}', settings.alibaba_cloud_access_key_id)
        and _valid_secret(settings.alibaba_cloud_access_key_secret)
        and (not settings.alibaba_cloud_security_token or _valid_secret(settings.alibaba_cloud_security_token))
        and 1 <= len(settings.aliyun_sms_sign_name.strip()) <= 128
        and not any(ord(c) < 32 or ord(c) == 127 for c in settings.aliyun_sms_sign_name)
        and re.fullmatch(r'SMS_[0-9]{1,32}', _sms_template(purpose))
        and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', settings.aliyun_sms_code_param)
    )
    return {
        'email': {'enabled': settings.auth_email_delivery_enabled, 'configured': email_configured,
                  'available': settings.auth_email_delivery_enabled and email_configured},
        'sms': {'enabled': settings.auth_sms_delivery_enabled, 'configured': sms_configured,
                'available': settings.auth_sms_delivery_enabled and sms_configured},
    }


def _valid_secret(value: str) -> bool:
    return 0 < len(value) <= 4096 and all(32 < ord(c) < 127 for c in value)


def send_verification(channel: str, destination: str, code: str, challenge_id: str, *, purpose: str = 'registration') -> None:
    if purpose not in {'registration', 'password_reset'} or channel not in {'email', 'sms'} or not configuration_status(purpose)[channel]['available']:
        raise DeliveryError('Verification delivery is not configured')
    try:
        if channel == 'email':
            _send_email(destination, code, challenge_id, purpose)
        else:
            asyncio.run(_send_sms(destination, code, challenge_id, purpose))
    except Exception:
        # Provider exceptions can contain credentials, the recipient, or the code.
        raise DeliveryError('Verification delivery failed') from None


def _send_email(destination: str, code: str, challenge_id: str, purpose: str = 'registration') -> None:
    message = EmailMessage()
    message['From'] = Address(settings.smtp_from_name, addr_spec=settings.smtp_from_address)
    message['To'] = destination
    reset = purpose == 'password_reset'
    message['Subject'] = 'Forma password reset / 重置密码' if reset else 'Forma registration verification / 注册验证'
    message['Date'] = formatdate(localtime=False, usegmt=True)
    domain = settings.smtp_from_address.rsplit('@', 1)[1]
    message['Message-ID'] = f'<{purpose}.{challenge_id}.{secrets.token_hex(8)}@{domain}>'
    message['Auto-Submitted'] = 'auto-generated'
    message.set_content((
        f'Your Forma password reset code is: {code}\n\n'
        'Enter this code on the password reset page within 10 minutes to choose a new password. '
        'If you did not request a password reset, ignore this message; your password has not changed. '
        'Never share this code.\n\n'
        f'您的 Forma 重置密码验证码是：{code}。请在 10 分钟内输入验证码并设置新密码。'
        '如果这不是您的操作，请忽略此邮件，您的密码不会改变。请勿向他人透露验证码。'
    ) if reset else (
        f'Your Forma verification code is: {code}\n\n'
        'Enter this code in the registration page within 10 minutes. '
        'After verification, an administrator must approve your account before you can sign in.\n'
        'If you did not request registration, ignore this message. Never share this code.\n\n'
        f'您的 Forma 注册验证码是：{code}。验证码 10 分钟内有效。'
        '验证后需等待管理员审批才能登录。如果这不是您的操作，请忽略此邮件。请勿向他人透露验证码。'
    ))
    context = ssl.create_default_context()
    if settings.smtp_tls_mode == 'ssl':
        connection = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port,
                                      timeout=settings.auth_delivery_transport_timeout_seconds, context=context)
    else:
        connection = smtplib.SMTP(settings.smtp_host, settings.smtp_port,
                                  timeout=settings.auth_delivery_transport_timeout_seconds)
    with connection as client:
        if settings.smtp_tls_mode == 'starttls':
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password)
        if client.send_message(message):
            raise DeliveryError('Recipient was refused')


def _authorization(query: str, headers: dict[str, str]) -> str:
    names = sorted(headers)
    signed_headers = ';'.join(names)
    canonical_headers = ''.join(f'{name}:{headers[name].strip()}\n' for name in names)
    empty_hash = hashlib.sha256(b'').hexdigest()
    canonical = '\n'.join(('POST', '/', query, canonical_headers, signed_headers, empty_hash))
    to_sign = 'ACS3-HMAC-SHA256\n' + hashlib.sha256(canonical.encode()).hexdigest()
    signature = hmac.new(settings.alibaba_cloud_access_key_secret.encode(), to_sign.encode(), hashlib.sha256).hexdigest()
    return (f'ACS3-HMAC-SHA256 Credential={settings.alibaba_cloud_access_key_id},'
            f'SignedHeaders={signed_headers},Signature={signature}')


async def _send_sms(destination: str, code: str, challenge_id: str, purpose: str = 'registration') -> None:
    if not re.fullmatch(r'\+861[3-9][0-9]{9}', destination) or not re.fullmatch(r'[0-9]{6}', code):
        raise DeliveryError('Invalid mainland China verification message')
    host = 'dysmsapi.aliyuncs.com'
    parameters = {
        'PhoneNumbers': destination[3:], 'SignName': settings.aliyun_sms_sign_name,
        'TemplateCode': _sms_template(purpose),
        'TemplateParam': json.dumps({settings.aliyun_sms_code_param: code}, ensure_ascii=False, separators=(',', ':')),
        'OutId': hashlib.sha256(challenge_id.encode()).hexdigest()[:32],
    }
    query = urlencode(sorted(parameters.items()), quote_via=quote, safe='~')
    headers = {
        'host': host, 'x-acs-action': 'SendSms', 'x-acs-version': '2017-05-25',
        'x-acs-content-sha256': hashlib.sha256(b'').hexdigest(),
        'x-acs-date': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'x-acs-signature-nonce': secrets.token_hex(16),
    }
    if settings.alibaba_cloud_security_token:
        headers['x-acs-security-token'] = settings.alibaba_cloud_security_token
    headers['authorization'] = _authorization(query, headers)
    timeout = settings.auth_delivery_transport_timeout_seconds
    request = httpx.Request('POST', f'https://{host}/?{query}', headers=headers, content=b'',
                            extensions={'timeout': dict.fromkeys(('connect', 'read', 'write', 'pool'), timeout)})
    async with asyncio.timeout(timeout), httpx.AsyncHTTPTransport(verify=True, trust_env=False, retries=0) as transport:
        # Direct transport avoids HTTPX's INFO logger exposing the signed URL.
        response = await transport.handle_async_request(request)
        try:
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 64 * 1024:
                    raise DeliveryError('Invalid SMS response')
            payload = json.loads(content)
            if response.status_code != 200 or not isinstance(payload, dict) or payload.get('Code') != 'OK':
                raise DeliveryError('SMS provider did not accept the message')
        finally:
            await response.aclose()
