"""Provider-neutral, cost-aware JSON calls for scientific knowledge synthesis."""

from dataclasses import asdict, dataclass
import json
import os
import re
import time
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener, urlopen


CC_SWITCH_HOSTS = {"localhost", "127.0.0.1", "::1"}
CC_SWITCH_DEFAULT_PORT = 15721
CC_SWITCH_PLACEHOLDER_TOKEN = "PROXY_MANAGED"


class LLMError(RuntimeError):
    pass


class LLMConfigurationError(LLMError):
    pass


class LLMResponseError(LLMError):
    pass


class LLMBudgetExceeded(LLMError):
    pass


def _is_cc_switch_url(base_url: str) -> bool:
    parsed = urlparse(str(base_url or "").strip())
    return parsed.hostname in CC_SWITCH_HOSTS and parsed.port == CC_SWITCH_DEFAULT_PORT


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    model: str
    api_key_env: str = "ELECTROCHEM_LLM_API_KEY"
    timeout_seconds: int = 120
    max_tokens: int = 4000
    max_input_chars: int = 60000
    temperature: float = 0.1
    max_retries: int = 2
    protocol: str = "auto"
    auth_mode: str = "auto"

    def __post_init__(self):
        base = str(self.base_url or "").strip().rstrip("/")
        model = str(self.model or "").strip()
        if not base:
            raise LLMConfigurationError("LLM base URL is required.")
        if not model:
            raise LLMConfigurationError("LLM model is required.")
        parsed = urlparse(base)
        is_loopback = parsed.hostname in CC_SWITCH_HOSTS
        if parsed.scheme not in {"https", "http"} or (parsed.scheme == "http" and not is_loopback):
            raise LLMConfigurationError("Use HTTPS for remote LLM endpoints; HTTP is allowed only for loopback local models.")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", self.api_key_env or ""):
            raise LLMConfigurationError("api_key_env must be an environment variable name.")
        if not 256 <= int(self.max_tokens) <= 32000:
            raise LLMConfigurationError("max_tokens must be between 256 and 32000.")
        if not 2000 <= int(self.max_input_chars) <= 250000:
            raise LLMConfigurationError("max_input_chars must be between 2000 and 250000.")
        if not 10 <= int(self.timeout_seconds) <= 600:
            raise LLMConfigurationError("timeout_seconds must be between 10 and 600.")
        if not 0 <= int(self.max_retries) <= 4:
            raise LLMConfigurationError("max_retries must be between 0 and 4.")

        is_cc_switch = _is_cc_switch_url(base)
        protocol = str(self.protocol or "auto").strip().lower()
        if protocol == "auto":
            protocol = "responses" if is_cc_switch else "chat_completions"
        if protocol not in {"chat_completions", "responses"}:
            raise LLMConfigurationError("protocol must be auto, chat_completions, or responses.")

        auth_mode = str(self.auth_mode or "auto").strip().lower()
        if auth_mode == "auto":
            auth_mode = "cc_switch" if is_cc_switch else "environment"
        if auth_mode not in {"environment", "cc_switch", "none"}:
            raise LLMConfigurationError("auth_mode must be auto, environment, cc_switch, or none.")
        if auth_mode == "cc_switch" and not is_cc_switch:
            raise LLMConfigurationError("CC-SWITCH authentication is allowed only on its loopback endpoint.")

        object.__setattr__(self, "base_url", base)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "timeout_seconds", int(self.timeout_seconds))
        object.__setattr__(self, "max_tokens", int(self.max_tokens))
        object.__setattr__(self, "max_input_chars", int(self.max_input_chars))
        object.__setattr__(self, "temperature", float(self.temperature))
        object.__setattr__(self, "max_retries", int(self.max_retries))
        object.__setattr__(self, "protocol", protocol)
        object.__setattr__(self, "auth_mode", auth_mode)

    @property
    def completion_url(self) -> str:
        suffix = "/responses" if self.protocol == "responses" else "/chat/completions"
        if self.base_url.endswith(suffix):
            return self.base_url
        return self.base_url + suffix

    def public_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class LLMResult:
    payload: Mapping
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict:
        return {
            "payload": dict(self.payload),
            "model": self.model,
            "usage": {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
            },
        }


def _default_transport(url: str, headers: dict, body: dict, timeout: int) -> dict:
    request = Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    parsed = urlparse(url)
    if parsed.hostname in CC_SWITCH_HOSTS:
        response_context = build_opener(ProxyHandler({})).open(request, timeout=timeout)
    else:
        response_context = urlopen(request, timeout=timeout)
    with response_context as response:
        return json.loads(response.read().decode("utf-8"))


def _json_content(value) -> dict:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise LLMResponseError("LLM did not return valid JSON: {}".format(error)) from error
    if not isinstance(parsed, dict):
        raise LLMResponseError("LLM JSON response must be an object.")
    return parsed


def _responses_text(response: Mapping) -> str:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    parts = []
    for item in response.get("output") or []:
        if not isinstance(item, Mapping) or item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if not isinstance(content, Mapping) or content.get("type") not in {"output_text", "text"}:
                continue
            text = content.get("text")
            if isinstance(text, Mapping):
                text = text.get("value")
            if text:
                parts.append(str(text))
    if not parts:
        raise LLMResponseError("Responses API result contains no assistant output text.")
    return "\n".join(parts)


class OpenAICompatibleProvider:
    """Minimal Chat Completions/Responses client using only the standard library."""

    def __init__(
        self,
        config: LLMConfig,
        *,
        transport: Callable[[str, dict, dict, int], dict] = _default_transport,
    ):
        self.config = config
        self.transport = transport

    def _headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ElectrochemHarness/LLMProvider",
        }
        if self.config.auth_mode == "cc_switch":
            headers["Authorization"] = "Bearer {}".format(CC_SWITCH_PLACEHOLDER_TOKEN)
        elif self.config.auth_mode == "environment":
            key = os.environ.get(self.config.api_key_env, "").strip()
            if key:
                headers["Authorization"] = "Bearer {}".format(key)
        return headers

    def _call(self, headers: dict, body: dict) -> dict:
        for attempt in range(self.config.max_retries + 1):
            try:
                return self.transport(
                    self.config.completion_url,
                    headers,
                    body,
                    self.config.timeout_seconds,
                )
            except HTTPError as error:
                retryable = error.code == 429 or 500 <= error.code <= 599
                if not retryable or attempt >= self.config.max_retries:
                    raise LLMError("LLM HTTP error {}".format(error.code)) from error
            except URLError as error:
                if attempt >= self.config.max_retries:
                    raise LLMError("LLM network error: {}".format(error.reason)) from error
            time.sleep(min(4, 2 ** attempt))
        raise LLMError("LLM request failed after retries.")

    def generate_json(self, system_prompt: str, payload: Mapping) -> LLMResult:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if len(serialized) > self.config.max_input_chars:
            raise LLMBudgetExceeded(
                "Evidence packet has {} characters, above the configured limit {}.".format(
                    len(serialized), self.config.max_input_chars
                )
            )
        if self.config.protocol == "responses":
            body = {
                "model": self.config.model,
                "instructions": str(system_prompt),
                "input": serialized,
                "max_output_tokens": self.config.max_tokens,
            }
        else:
            body = {
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": str(system_prompt)},
                    {"role": "user", "content": serialized},
                ],
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
                "response_format": {"type": "json_object"},
            }
        response = self._call(self._headers(), body)
        usage = response.get("usage") or {}
        if self.config.protocol == "responses":
            if response.get("status") not in {None, "completed"}:
                raise LLMResponseError("Responses API request ended with status {}.".format(response.get("status")))
            content = _responses_text(response)
            prompt_tokens = int(usage.get("input_tokens", 0) or 0)
            completion_tokens = int(usage.get("output_tokens", 0) or 0)
        else:
            try:
                content = response["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as error:
                raise LLMResponseError("LLM response is missing choices[0].message.content.") from error
            prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        return LLMResult(
            payload=_json_content(content),
            model=str(response.get("model") or self.config.model),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=int(usage.get("total_tokens", prompt_tokens + completion_tokens) or 0),
        )
