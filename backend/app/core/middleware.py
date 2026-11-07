from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        received_bytes = 0
        oversized = False
        response_messages: list[Message] = []

        async def limited_receive() -> Message:
            nonlocal received_bytes, oversized
            if oversized:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_bytes:
                    oversized = True
                    return {"type": "http.disconnect"}
            return message

        async def buffered_send(message: Message) -> None:
            response_messages.append(message)

        try:
            await self.app(scope, limited_receive, buffered_send)
        except Exception:
            if not oversized:
                raise

        if oversized:
            await send({"type": "http.response.start", "status": 413, "headers": [
                (b"content-type", b"application/json"),
                (b"x-content-type-options", b"nosniff"),
                (b"x-frame-options", b"DENY"),
                (b"referrer-policy", b"no-referrer"),
                (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
            ]})
            await send({"type": "http.response.body", "body": b'{"error":{"code":"payload_too_large","message":"Request body is too large"}}'})
            return

        for message in response_messages:
            await send(message)
