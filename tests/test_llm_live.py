"""真实 LLM 适配层测试：think 剥离 / 端点解析 / env 装配（MockTransport，无网络）。"""

import httpx
import pytest

from quant_sentiment.llm_live import AnthropicLLM, OpenAICompatLLM, make_llm_from_env, strip_think


def test_strip_think_removes_inline_cot():
    text = "<think>推理过程 {可能含花括号}</think>{\"label\":\"利好\",\"confidence\":0.9}"
    assert strip_think(text) == '{"label":"利好","confidence":0.9}'


def test_strip_think_keeps_plain_text():
    assert strip_think('{"label":"中性"}') == '{"label":"中性"}'


def test_openai_compat_generate():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        body = request.read().decode("utf-8")
        assert "测试提示词" in body
        return httpx.Response(200, json={"choices": [{"message": {"content": "<think>x</think>OK"}}]})

    llm = OpenAICompatLLM(
        base_url="https://api.minimaxi.com/v1",
        api_key="sk-test",
        model="MiniMax-M3",
        transport=httpx.MockTransport(handler),
    )
    assert llm.generate("测试提示词") == "OK"


def test_anthropic_generate():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "sk-test"
        return httpx.Response(200, json={"content": [{"type": "text", "text": "你好"}]})

    llm = AnthropicLLM(
        base_url="https://api.anthropic.com",
        api_key="sk-test",
        model="claude-haiku-4-5-20251001",
        transport=httpx.MockTransport(handler),
    )
    assert llm.generate("hi") == "你好"


def test_env_resolution_minimax(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-mm")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    llm = make_llm_from_env()
    assert isinstance(llm, OpenAICompatLLM)
    assert llm.base_url == "https://api.minimaxi.com/v1"
    assert llm.model  # 有默认文本模型


def test_env_resolution_llm_triple_missing_base_raises(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    with pytest.raises(RuntimeError):
        make_llm_from_env()


def test_env_resolution_anthropic_mode(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.anthropic.com")
    monkeypatch.setenv("LLM_MODEL", "claude-haiku-4-5-20251001")
    monkeypatch.setenv("LLM_MODE", "anthropic")
    llm = make_llm_from_env()
    assert isinstance(llm, AnthropicLLM)


def test_env_resolution_no_key_returns_none(monkeypatch):
    for key in ("LLM_API_KEY", "MINIMAX_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    assert make_llm_from_env() is None
