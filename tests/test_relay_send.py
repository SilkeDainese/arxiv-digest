import relay.api.send as relay_send


class _FakeHandler:
    def __init__(self):
        self.response = None

    def _respond(self, status, body):
        self.response = (status, body)


def test_relay_get_only_returns_health_status():
    fake = _FakeHandler()

    relay_send.handler.do_GET(fake)

    assert fake.response == (
        200,
        {"status": "arXiv Digest relay is running"},
    )
