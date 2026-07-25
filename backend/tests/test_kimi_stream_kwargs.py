"""Kimi 参数与 stream/chat 一致性。"""

from __future__ import annotations

from app.llm.client import LLMClient, ModelEndpoint


def test_kimi_chat_and_stream_kwargs_disable_thinking():
    client = LLMClient()
    ep = ModelEndpoint(
        provider="openai",
        base_url="https://api.moonshot.cn/v1",
        api_key="sk-test",
        model="kimi-k2.6",
    )
    msgs = [{"role": "user", "content": "hi"}]
    kwargs = client._openai_chat_kwargs(ep, msgs, temperature=0.9, max_tokens=100)
    assert "temperature" not in kwargs
    assert kwargs.get("extra_body") == {"thinking": {"type": "disabled"}}

    # stream 路径复用同一 kwargs 构建（再加 stream=True）
    stream_kwargs = dict(kwargs)
    stream_kwargs["stream"] = True
    assert "temperature" not in stream_kwargs
    assert stream_kwargs["extra_body"]["thinking"]["type"] == "disabled"


def test_non_kimi_keeps_temperature():
    client = LLMClient()
    ep = ModelEndpoint(
        provider="openai",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-4o",
    )
    kwargs = client._openai_chat_kwargs(ep, [{"role": "user", "content": "hi"}], 0.5, 100)
    assert kwargs["temperature"] == 0.5
    assert "extra_body" not in kwargs
