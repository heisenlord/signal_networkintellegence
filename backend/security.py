"""Transport protections and bounded admission for the single-process deployment."""
import time
from collections import OrderedDict
from uuid import uuid4

from starlette.responses import JSONResponse


class SecurityMiddleware:
    def __init__(self, app, settings):
        self.app, self.settings = app, settings
        self.clients = OrderedDict()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id

        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend([
                    (b"x-request-id", request_id.encode()), (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    # React Flow/Recharts require inline style attributes. Scripts stay same-origin.
                    (b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"),
                ])
                if self.settings.signal_environment == "production":
                    headers.append((b"strict-transport-security", b"max-age=31536000"))
                message["headers"] = headers
            await send(message)

        async def reject(status, detail, headers=None):
            response = JSONResponse({"detail": detail, "request_id": request_id}, status_code=status, headers=headers)
            await response(scope, receive, secure_send)

        # Health checks must remain available under load.
        if scope["path"] != "/api/health":
            now = time.monotonic()
            client = (scope.get("client") or ("unknown",))[0]
            started, count = self.clients.pop(client, (now, 0))
            if now - started >= 60:
                started, count = now, 0
            self.clients[client] = (started, count + 1)
            if len(self.clients) > 10000:
                self.clients.popitem(last=False)
            if count >= self.settings.signal_requests_per_minute:
                return await reject(429, "Request limit exceeded", {"Retry-After": str(max(1, int(60 - now + started)))})

        # Count received bytes, including chunked bodies, before JSON parsing.
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.settings.signal_max_body_bytes:
                return await reject(413, "Request body is too large")
            if not message.get("more_body", False):
                break
        consumed = False

        async def replay():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, secure_send)
