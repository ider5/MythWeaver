import pytest

from app.llm.client import ChatMessage, MockLLMClient, set_llm_client
from app.services.story_bible import match_alias_mentions
from app.models.entities import Character


@pytest.mark.asyncio
async def test_mock_chat_and_stream():
    client = MockLLMClient(chat_responses=['{"ok": true}'], stream_text="流式章节", smart=False)
    set_llm_client(client)
    result = await client.chat([ChatMessage(role="user", content="hi")])
    assert "ok" in result.text

    parts = []
    async for chunk in client.stream([{"role": "user", "content": "写"}]):
        if "delta_text" in chunk:
            parts.append(chunk["delta_text"])
        if chunk.get("done"):
            assert chunk["text"] == "流式章节"
    assert "".join(parts) == "流式章节"


@pytest.mark.asyncio
async def test_mock_embed():
    client = MockLLMClient(embed_dim=8)
    vectors, tokens = await client.embed(["测试文本", "另一段"])
    assert len(vectors) == 2
    assert len(vectors[0]) == 8
    assert tokens > 0


def test_alias_match_empty_bible():
    issues = match_alias_mentions("甲" * 600, [])
    assert issues and issues[0]["type"] == "alias"


def test_alias_match_with_characters():
    c = Character(novel_id=1, name="张三", aliases=["三哥"])
    issues = match_alias_mentions("张三与三哥同行", [c])
    assert issues == []
