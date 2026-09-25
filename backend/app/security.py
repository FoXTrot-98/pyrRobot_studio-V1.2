"""Local-only default; token authentication for explicitly configured access."""
import base64
import hmac
import ipaddress
import os
import re
from starlette.responses import JSONResponse


def studio_origins():
    return [value.strip() for value in os.environ.get('PYROBOT_STUDIO_ORIGINS',
        'http://localhost:5173,http://127.0.0.1:5173').split(',') if value.strip()]


class StudioSecurity:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket'):
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        origin = headers.get(b'origin', b'').decode()
        token = os.environ.get('PYROBOT_STUDIO_TOKEN', '')
        host = scope.get('client', ('', 0))[0]
        try: local = ipaddress.ip_address(host).is_loopback
        except ValueError: local = host == 'testclient'
        detail = None
        status = 403
        if origin and origin not in studio_origins():
            detail = 'Studio origin is not allowed'
        elif not token and not local:
            detail = 'Studio is local-only; use the authenticated robot agent for remote deployment'
        elif token:
            if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', token):
                detail = 'PYROBOT_STUDIO_TOKEN must be 32-128 URL-safe characters'
            elif not local and scope.get('scheme') not in ('https', 'wss'):
                detail = 'Remote Studio authentication requires TLS'
            else:
                supplied = headers.get(b'authorization', b'').decode()
                if scope['type'] == 'websocket':
                    supplied = ''
                    for protocol in scope.get('subprotocols', []):
                        if protocol.startswith('auth.'):
                            try:
                                value = protocol[5:]
                                supplied = 'Bearer ' + base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)).decode()
                            except (ValueError, UnicodeError): pass
                if not hmac.compare_digest(supplied.encode(), ('Bearer ' + token).encode()):
                    detail, status = 'Studio authentication required', 401
        if detail:
            if scope['type'] == 'websocket':
                await send({'type': 'websocket.close', 'code': 1008})
            else:
                await JSONResponse({'detail': detail}, status_code=status)(scope, receive, send)
            return
        await self.app(scope, receive, send)
