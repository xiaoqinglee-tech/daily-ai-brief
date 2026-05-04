"""A lightweight, OpenAI-compatible LLM client.

适用于任何兼容 OpenAI Chat Completions 协议的服务。

Features:
    - 普通文本对话 (chat)
    - JSON 结构化输出 (chat_json)
    - 流式响应 (chat_stream)
    - 自动重试 (指数退避,区分客户端/服务端错误)
    - 标准 logging,无 print 副作用

Usage:
    from llm import LLMClient

    # 方式 1:从环境变量加载 (LLM_MODEL / LLM_API_KEY / LLM_BASE_URL)
    client = LLMClient.from_env()

    # 方式 2:显式传参
    client = LLMClient(
        model="<model-name>",
        api_key="<your-api-key>",
        base_url="<api-base-url>",
    )

    text = client.chat([{"role": "user", "content": "Hello"}])
    data = client.chat_json([{"role": "user", "content": "返回 JSON"}])
    for chunk in client.chat_stream([{"role": "user", "content": "Hi"}]):
        print(chunk, end="", flush=True)
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Iterator, List, Optional

from openai import APIError, APITimeoutError, OpenAI, RateLimitError

logger = logging.getLogger(__name__)


class LLMClient:
    """OpenAI-compatible LLM client with retry and JSON mode support."""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str,
        timeout: int = 60,
        max_retries: int = 3,
        retry_base_delay: float = 2.0,
    ) -> None:
        if not all([model, api_key, base_url]):
            raise ValueError("model, api_key, base_url are all required")

        self.model = model
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        logger.info("LLMClient initialized: model=%s, base_url=%s", model, base_url)

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------
    @classmethod
    def from_env(
        cls,
        model_env: str = "LLM_MODEL",
        api_key_env: str = "LLM_API_KEY",
        base_url_env: str = "LLM_BASE_URL",
        **kwargs: Any,
    ) -> "LLMClient":
        """从环境变量构造。环境变量名可自定义,方便一个进程同时用多个 LLM。"""
        model = os.getenv(model_env)
        api_key = os.getenv(api_key_env)
        base_url = os.getenv(base_url_env)
        if not all([model, api_key, base_url]):
            raise ValueError(
                f"Missing env vars. Required: {model_env}, {api_key_env}, {base_url_env}"
            )
        return cls(model=model, api_key=api_key, base_url=base_url, **kwargs)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        thinking: Optional[bool] = None,
        **extra: Any,
    ) -> str:
        """普通文本对话,返回 assistant 的 content 字符串。

        Args:
            thinking: 控制是否在请求中传递 enable_thinking 参数。
                None = 不传(由后端决定行为)
                True / False = 显式传递对应值
                是否生效取决于后端 API 与所选模型,客户端不做判断。
        """
        return self._call(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=False,
            thinking=thinking,
            **extra,
        )

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        use_native_json_mode: bool = True,
        thinking: Optional[bool] = None,
        **extra: Any,
    ) -> Any:
        """要求 LLM 返回 JSON,自动 json.loads 后返回 dict/list。

        Args:
            use_native_json_mode: 是否使用 OpenAI 协议原生的
                response_format={"type": "json_object"}。设为 False 时
                退化为纯 prompt 引导 + 自己提取 JSON,兼容性更好。
            thinking: 见 chat() 同名参数。

        注意:无论哪种模式,messages 里都应明确告诉 LLM 输出 JSON。
        """
        text = self._call(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=use_native_json_mode,
            thinking=thinking,
            **extra,
        )
        return self._parse_json(text)

    @staticmethod
    def _parse_json(text: str) -> Any:
        """从 LLM 输出中提取 JSON。

        兼容三种情况:
        1. 纯 JSON
        2. ```json ... ``` 包裹的 JSON
        3. 文本中混入 JSON(取第一个 { 到最后一个 })
        """
        text = text.strip()

        # 情况 2:剥掉 markdown code fence
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        # 情况 1:直接尝试解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 情况 3:从文本中提取 JSON 子串
        for open_char, close_char in [("{", "}"), ("[", "]")]:
            start = text.find(open_char)
            end = text.rfind(close_char)
            if start != -1 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    continue

        logger.error("Failed to extract JSON from LLM output: %s", text)
        raise ValueError(f"Cannot parse JSON from LLM output: {text[:200]}...")

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        thinking: Optional[bool] = None,
        **extra: Any,
    ) -> Iterator[str]:
        """流式响应,yield 每个 token chunk(字符串)。

        Args:
            thinking: 见 chat() 同名参数。
        """
        kwargs = self._build_kwargs(
            messages, temperature, max_tokens, json_mode=False, thinking=thinking
        )
        kwargs["stream"] = True
        kwargs.update(extra)

        logger.debug("LLM stream call, model=%s", self.model)
        try:
            response = self._client.chat.completions.create(**kwargs)
            for chunk in response:
                # 流末尾可能是没有 choices 的元信息 chunk,跳过
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", None) or ""
                if content:
                    yield content
        except Exception as e:
            logger.exception("LLM stream error: %s", e)
            raise

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _build_kwargs(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: Optional[int],
        json_mode: bool,
        thinking: Optional[bool] = None,
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if thinking is not None:
            # OpenAI SDK 不识别 enable_thinking 字段,通过 extra_body 透传给后端
            kwargs["extra_body"] = {"enable_thinking": thinking}
        return kwargs

    def _call(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float,
        max_tokens: Optional[int],
        json_mode: bool,
        thinking: Optional[bool] = None,
        **extra: Any,
    ) -> str:
        kwargs = self._build_kwargs(
            messages, temperature, max_tokens, json_mode, thinking
        )
        kwargs.update(extra)

        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                t0 = time.time()
                response = self._client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content or ""
                self._log_usage(response, time.time() - t0)
                return content
            except APITimeoutError as e:
                last_err = e
                self._sleep_before_retry(attempt, e)
            except RateLimitError as e:
                last_err = e
                self._sleep_before_retry(attempt, e)
            except APIError as e:
                # 客户端错误(4xx,除 429)不重试,服务端错误重试
                status = getattr(e, "status_code", None)
                if status and 400 <= status < 500 and status != 429:
                    logger.error("LLM client error %s (no retry): %s", status, e)
                    raise
                last_err = e
                self._sleep_before_retry(attempt, e)
            except Exception as e:
                logger.exception("LLM call unexpected error: %s", e)
                raise

        raise RuntimeError(f"LLM call failed after {self.max_retries} attempts") from last_err

    def _sleep_before_retry(self, attempt: int, err: Exception) -> None:
        """重试前 sleep,带日志。最后一次尝试不 sleep。"""
        if attempt < self.max_retries:
            wait = self.retry_base_delay ** attempt
            logger.warning(
                "LLM call failed (%d/%d): %s. Retrying in %.1fs...",
                attempt, self.max_retries, err, wait,
            )
            time.sleep(wait)
        else:
            logger.error(
                "LLM call failed after %d attempts: %s", self.max_retries, err,
            )

    @staticmethod
    def _log_usage(response: Any, elapsed: float) -> None:
        usage = getattr(response, "usage", None)
        if usage:
            logger.info(
                "LLM ok: %.2fs, tokens prompt=%s completion=%s total=%s",
                elapsed,
                usage.prompt_tokens,
                usage.completion_tokens,
                usage.total_tokens,
            )
        else:
            logger.info("LLM ok: %.2fs (no usage info)", elapsed)


# ----------------------------------------------------------------------
# Self-test
# ----------------------------------------------------------------------
if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(override=False)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    client = LLMClient.from_env()

    # Test 1: plain chat
    print("\n=== Test 1: plain chat ===")
    print(client.chat([{"role": "user", "content": "用一句话介绍 LLM Agent。"}]))

    # Test 2: thinking on vs off
    print("\n=== Test 2: thinking on vs off ===")
    test_msgs = [
        {
            "role": "system",
            "content": (
                "你是论文筛选助手。判断标题是否跟 LLM Agent 相关,"
                "严格只输出 JSON: {\"relevant\": true/false, \"reason\": \"一句话理由\"}"
            ),
        },
        {"role": "user", "content": "ReAct: Synergizing Reasoning and Acting in Language Models"},
    ]

    for thinking_on in [True, False]:
        label = "ON " if thinking_on else "OFF"
        t0 = time.time()
        try:
            result = client.chat_json(
                test_msgs,
                use_native_json_mode=False,
                thinking=thinking_on,
            )
            elapsed = time.time() - t0
            print(f"[thinking={label}] {elapsed:5.2f}s -> {result}")
        except Exception as e:
            print(f"[thinking={label}] failed: {e}")

    # Test 3: streaming
    print("\n=== Test 3: streaming ===")
    for chunk in client.chat_stream([{"role": "user", "content": "数 1 到 5"}]):
        print(chunk, end="", flush=True)
    print()
