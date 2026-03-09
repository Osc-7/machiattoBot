from shuiyuan_integration.client import ShuiyuanClient


class _Resp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def test_toggle_retort_prefers_put_retorts_without_json(monkeypatch):
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
    # 优先使用 ShuiyuanSJTU/retort 的 PUT /retorts/:post_id（无 .json）
    assert calls[0][0] == "PUT"
    assert calls[0][1].endswith("/retorts/123")
    assert calls[0][2]["data"]["retort"] == "thumbsup"


def test_toggle_retort_fallbacks_from_json_to_legacy_retorts(monkeypatch):
    calls = []
    # 先尝试无 .json（404），再尝试 .json（201）
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
    # 第一次：PUT /retorts/456（无 .json）
    assert calls[0][1].endswith("/retorts/456")
    # 第二次：PUT /retorts/456.json（fallback）
    assert calls[1][1].endswith("/retorts/456.json")


def test_toggle_retort_fallbacks_to_discourse_reactions(monkeypatch):
    calls = []
    # 依次尝试：
    # 1) PUT /retorts/:id
    # 2) PUT /retorts/:id.json
    # 3) POST /retorts/:id.json
    # 4) POST /retorts/:id
    # 5) POST /discourse-reactions/.../toggle.json
    responses = [
        _Resp(404),
        _Resp(404),
        _Resp(404),
        _Resp(404),
        _Resp(204),
    ]

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
    assert len(calls) == 5
    # 最终回退到 discourse-reactions 插件的 POST /discourse-reactions/.../toggle.json
    assert calls[-1][0] == "POST"
    assert "/discourse-reactions/posts/789/custom-reactions/%2B1/toggle.json" in calls[-1][1]
