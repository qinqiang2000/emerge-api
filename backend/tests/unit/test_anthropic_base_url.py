"""AnthropicProvider must route through the configured gateway, never direct.

Hard rule: no direct api.anthropic.com (MEMORY:feedback_anthropic_no_direct_api).
The provider resolves its endpoint from `base_url`; these pin the URL math so a
regression can't silently send extract traffic to api.anthropic.com.
"""
from app.provider.anthropic import _API_URL, _messages_url


def test_no_base_url_falls_back_to_constant():
    assert _messages_url(None) == _API_URL
    assert _messages_url("") == _API_URL


def test_host_root_gets_v1_messages_appended():
    assert _messages_url("https://gw.example.com") == "https://gw.example.com/v1/messages"
    assert _messages_url("https://gw.example.com/") == "https://gw.example.com/v1/messages"


def test_base_url_with_v1_suffix():
    assert _messages_url("https://gw.example.com/v1") == "https://gw.example.com/v1/messages"


def test_full_messages_url_passthrough():
    url = "https://gw.example.com/v1/messages"
    assert _messages_url(url) == url
