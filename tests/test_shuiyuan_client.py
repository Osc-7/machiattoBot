from shuiyuan_integration.client import ShuiyuanClient


class _Resp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def test_toggle_retort_prefers_retorts_json(monkeypatch):
    calls = []

    def _fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _Resp(200)

    monkeypatch.setattr("shuiyuan_integration.client._ensure_rate_limit", lambda: None)
    monkeypatch.setattr("shuiyuan_integration.client.requests.request", _fake_request)

    client = ShuiyuanClient(user_api_key="k")
    ok, status, detail = client.toggle_retort(post_id=123, emoji="thumbsup")

    assert ok is True
    assert status == 200
    assert detail == ""
    assert len(calls) == 1
    assert calls[0][0] == "POST"
    assert calls[0][1].endswith("/retorts/123.json")
    assert calls[0][2]["data"]["retort"] == "thumbsup"


def test_toggle_retort_fallbacks_from_json_to_legacy_retorts(monkeypatch):
    calls = []
    responses = [_Resp(404, "not found"), _Resp(201)]

    def _fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return responses[len(calls) - 1]

    monkeypatch.setattr("shuiyuan_integration.client._ensure_rate_limit", lambda: None)
    monkeypatch.setattr("shuiyuan_integration.client.requests.request", _fake_request)

    client = ShuiyuanClient(user_api_key="k")
    ok, status, detail = client.toggle_retort(post_id=456, emoji="heart")

    assert ok is True
    assert status == 201
    assert detail == ""
    assert len(calls) == 2
    assert calls[0][1].endswith("/retorts/456.json")
    assert calls[1][1].endswith("/retorts/456")


def test_toggle_retort_fallbacks_to_discourse_reactions(monkeypatch):
    calls = []
    responses = [_Resp(404), _Resp(404), _Resp(204)]

    def _fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return responses[len(calls) - 1]

    monkeypatch.setattr("shuiyuan_integration.client._ensure_rate_limit", lambda: None)
    monkeypatch.setattr("shuiyuan_integration.client.requests.request", _fake_request)

    client = ShuiyuanClient(user_api_key="k")
    ok, status, detail = client.toggle_retort(post_id=789, emoji="+1")

    assert ok is True
    assert status == 204
    assert detail == ""
    assert len(calls) == 3
    assert calls[2][0] == "POST"
    assert "/discourse-reactions/posts/789/custom-reactions/%2B1/toggle.json" in calls[2][1]
