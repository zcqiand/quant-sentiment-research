"""真实 LLM 适配层：把 HTTP 端点包成 ``generate(prompt) -> str``。

装配顺序（``make_llm_from_env``）：

1. ``LLM_API_KEY`` + ``LLM_BASE_URL`` + ``LLM_MODEL``（缺一即 RuntimeError，fail-fast）；
   ``LLM_MODE``＝``anthropic`` 走 Anthropic 端点，否则走 OpenAI 兼容端点。
2. ``MINIMAX_API_KEY``（本机 .claude/settings.local.json 注入）：
   base＝``MINIMAX_API_HOST``（缺省 https://api.minimaxi.com）拼 ``/v1``，
   model＝``MINIMAX_MODEL``（缺省 MiniMax-M3，注意别用 image-01 之类的图像模型）。
3. 兼容 ``OPENAI_API_KEY`` / ``ANTHROPIC_API_KEY`` 两条旧路。
4. 都没有 → 返回 None，由调用方回退 FakeLLM。

MiniMax-M3 会内联 ``<think>…</think>`` 思维链，所有响应统一 ``strip_think`` 剥离
（记忆总账 minimax-m3-integration-pitfalls 指纹）。
"""

from __future__ import annotations

import os
import re

import httpx

THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_think(text: str) -> str:
    """剥离内联思维链（MiniMax-M3 指纹），返回去空白后的正文。"""
    return THINK_RE.sub("", text).strip()


class OpenAICompatLLM:
    """OpenAI 兼容 chat/completions 端点适配器。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._transport = transport

    def generate(self, prompt: str) -> str:
        with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        return strip_think(content)


class AnthropicLLM:
    """Anthropic /v1/messages 端点适配器。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._transport = transport

    def generate(self, prompt: str) -> str:
        with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
            resp = client.post(
                f"{self.base_url}/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": self.model,
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            content = resp.json()["content"][0]["text"]
        return strip_think(content)


DEFAULT_MINIMAX_HOST = "https://api.minimaxi.com"
DEFAULT_MINIMAX_MODEL = "MiniMax-M3"


def make_llm_from_env() -> OpenAICompatLLM | AnthropicLLM | None:
    """按模块 docstring 的装配顺序从环境变量构造 LLM；无 Key 返回 None。"""
    if os.getenv("LLM_API_KEY"):
        base = os.getenv("LLM_BASE_URL")
        model = os.getenv("LLM_MODEL")
        if not base or not model:
            raise RuntimeError(
                "LLM_API_KEY 已设置但缺 LLM_BASE_URL / LLM_MODEL——fail-fast，不做默认值兜底"
            )
        mode = os.getenv("LLM_MODE", "openai").strip().lower()
        if mode == "anthropic":
            return AnthropicLLM(base_url=base, api_key=os.environ["LLM_API_KEY"], model=model)
        return OpenAICompatLLM(base_url=base, api_key=os.environ["LLM_API_KEY"], model=model)

    if os.getenv("MINIMAX_API_KEY"):
        host = os.getenv("MINIMAX_API_HOST", DEFAULT_MINIMAX_HOST).rstrip("/")
        base = host if host.endswith("/v1") else f"{host}/v1"
        model = os.getenv("MINIMAX_MODEL") or DEFAULT_MINIMAX_MODEL
        return OpenAICompatLLM(base_url=base, api_key=os.environ["MINIMAX_API_KEY"], model=model)

    if os.getenv("OPENAI_API_KEY"):
        return OpenAICompatLLM(
            base_url="https://api.openai.com/v1",
            api_key=os.environ["OPENAI_API_KEY"],
            model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        )

    if os.getenv("ANTHROPIC_API_KEY"):
        return AnthropicLLM(
            base_url="https://api.anthropic.com",
            api_key=os.environ["ANTHROPIC_API_KEY"],
            model=os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001"),
        )

    return None


__all__ = ["strip_think", "OpenAICompatLLM", "AnthropicLLM", "make_llm_from_env"]
