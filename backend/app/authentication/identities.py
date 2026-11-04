"""Canonical mainland China mobile numbers, including local and +86 forms."""
import re


def canonical_phone(value: str) -> str:
    number = re.sub(r'[ ()-]', '', value.strip())
    if number.startswith('0086'):
        number = '+' + number[2:]
    if re.fullmatch(r'1[3-9][0-9]{9}', number):
        number = '+86' + number
    if not re.fullmatch(r'\+861[3-9][0-9]{9}', number):
        raise ValueError('Enter an 11-digit mainland China mobile number (+86)')
    return number
