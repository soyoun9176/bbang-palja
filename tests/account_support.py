"""Stable, unique phone identifiers for existing domain test fixtures."""
import itertools

_numbers=itertools.count(50000000)
_phones={'김소연':'010-1234-5678','꾸미는사람':'010-1234-5678','기존구매자':'010-0000-0000'}


def phone_for(name):
    if name not in _phones:
        number=f'{next(_numbers):08d}'
        _phones[name]=f'010-{number[:4]}-{number[4:]}'
    return _phones[name]


def account_payload(path,body):
    if body and path in ('/api/auth/register','/api/auth/login','/api/staff/manual-sale') and 'phone' not in body and 'name' in body:
        return {**body,'phone':phone_for(body['name'])}
    return body
