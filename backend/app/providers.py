from __future__ import annotations

import base64
import json
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .config import TEST_FAKE_PROVIDER, normalize_provider_name, test_provider_enabled
from .translation_batches import manage_project_prompt_context


class ProviderError(RuntimeError):
    pass


@dataclass
class TranslationItem:
    id: int | str
    translation: str


def _normalize_translation_id(value: Any) -> int | str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value).strip()
    if re.fullmatch(r"-?(0|[1-9]\d*)", text):
        return int(text)
    return text


def _extract_placeholders(text: str) -> list[str]:
    patterns = [
        r"\{[^{}]+\}",
        r"%[sdif]",
        r"##\d+",
        r"\[(?!/?color\b)(?:[A-Za-z]+\d+|\d+)\]",
        r"\[[a-zA-Z]+[^\]]*\]",
        r"\[/[a-zA-Z]+\]",
        r"<[^>]+>",
    ]
    hits: list[str] = []
    for pattern in patterns:
        hits.extend(re.findall(pattern, text))
    return hits


def _newline_suffix(source: str) -> str:
    actual = source.count("\n")
    escaped = source.count("\\n")
    return ("\n" * actual) + ("\\n" * escaped)


def _test_fake_translate_row(row: dict[str, Any]) -> str:
    row_id = _normalize_translation_id(row["id"])
    term_hits = row.get("term_hits") or []
    term_text = ""
    if term_hits:
        targets = [str(hit.get("target", "")).strip() for hit in term_hits if hit.get("target")]
        if targets:
            term_text = " " + " ".join(targets[:2])
    placeholders = " ".join(_extract_placeholders(str(row.get("source", ""))))
    placeholder_text = f" {placeholders}" if placeholders else ""
    display_id = str(row_id) if isinstance(row_id, int) else "row"
    base = f"TestFake {display_id}{term_text}{placeholder_text}".strip()
    return base + _newline_suffix(str(row.get("source", "")))


def test_fake_translate_batch(rows: list[dict[str, Any]], settings: dict[str, Any]) -> list[TranslationItem]:
    if not test_provider_enabled():
        raise ProviderError("test fake provider is disabled")
    return [TranslationItem(id=_normalize_translation_id(row["id"]), translation=_test_fake_translate_row(row)) for row in rows]



test_fake_translate_batch.__test__ = False

def build_prompt(rows: list[dict[str, Any]], project_prompt: str, *, ascii_escape: bool = False) -> str:
    payload = "\n".join(json.dumps(row, ensure_ascii=ascii_escape) for row in rows)
    guidance = json.dumps(project_prompt, ensure_ascii=True) if ascii_escape else project_prompt
    guidance_label = "Project guidance JSON string; decode Unicode escapes before applying it:" if ascii_escape else "Project guidance:"
    escape_note = "Chinese text may be represented as Unicode escapes; decode and translate it normally. " if ascii_escape else ""
    return (
        "You are translating a game localization workpack. "
        f"{escape_note}"
        "Return JSONL only. Each line must be {\"id\": number|string, \"translation\": string}. "
        "Preserve placeholders, tags, escaped newlines, actual newlines, and row order exactly. "
        "Do not add explanations.\n\n"
        f"{guidance_label}\n{guidance}\n\n"
        f"Rows:\n{payload}"
    )


async def openai_responses_translate_batch(
    rows: list[dict[str, Any]],
    settings: dict[str, Any],
    project_prompt: str,
) -> list[TranslationItem]:
    api_key = settings.get("api_key")
    if not api_key:
        raise ProviderError("api_key is required for responses provider")
    base_url = str(settings.get("base_url") or "https://api.openai.com").rstrip("/")
    model = settings.get("model") or "gpt-5.5"
    reasoning_effort = settings.get("reasoning_effort") or "medium"
    max_output_tokens = int(settings.get("max_output_tokens") or 8192)
    timeout_seconds = int(settings.get("provider_timeout_seconds") or 120)
    body = {
        "model": model,
        "input": build_prompt(rows, project_prompt),
        "reasoning": {"effort": reasoning_effort},
        "max_output_tokens": max_output_tokens,
    }
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            f"{base_url}/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
        )
    if response.status_code >= 400:
        raise ProviderError(f"responses failed: {response.status_code} {response.text[:500]}")
    payload = response.json()
    text = payload.get("output_text") or _collect_response_text(payload)
    return parse_jsonl_items(text)


async def openai_chat_translate_batch(
    rows: list[dict[str, Any]],
    settings: dict[str, Any],
    project_prompt: str,
) -> list[TranslationItem]:
    api_key = settings.get("api_key")
    if not api_key:
        raise ProviderError("api_key is required for OpenAI chat-compatible provider")
    base_url = str(settings.get("base_url") or "https://api.openai.com").rstrip("/")
    model = settings.get("model") or "gpt-5.5"
    timeout_seconds = int(settings.get("provider_timeout_seconds") or 120)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return strict JSONL only. Do not include prose, markdown fences, or explanations."},
            {"role": "user", "content": build_prompt(rows, project_prompt, ascii_escape=True)},
        ],
        "max_tokens": int(settings.get("max_output_tokens") or 8192),
    }
    reasoning_effort = str(settings.get("reasoning_effort") or "").strip()
    if reasoning_effort and reasoning_effort not in {"none", "adaptive"}:
        body["reasoning"] = {"effort": reasoning_effort}
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
        )
    if response.status_code >= 400:
        raise ProviderError(f"openai chat-compatible provider failed: {response.status_code} {response.text[:500]}")
    return parse_jsonl_items(_collect_openai_chat_text(response.json()))


async def anthropic_messages_translate_batch(
    rows: list[dict[str, Any]],
    settings: dict[str, Any],
    project_prompt: str,
) -> list[TranslationItem]:
    api_key = settings.get("api_key")
    if not api_key:
        raise ProviderError("api_key is required for Claude provider")
    base_url = str(settings.get("base_url") or "https://api.anthropic.com").rstrip("/")
    model = settings.get("model") or "claude-sonnet-4-6"
    timeout_seconds = int(settings.get("provider_timeout_seconds") or 180)
    body = {
        "model": model,
        "max_tokens": int(settings.get("max_output_tokens") or 8192),
        "system": "Return strict JSONL only. Do not include prose, markdown fences, or explanations.",
        "messages": [
            {
                "role": "user",
                "content": build_prompt(rows, project_prompt),
            }
        ],
    }
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            f"{base_url}/v1/messages",
            headers={
                "x-api-key": str(api_key),
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=body,
        )
    if response.status_code >= 400:
        raise ProviderError(f"claude messages failed: {response.status_code} {response.text[:500]}")
    payload = response.json()
    return parse_jsonl_items(_collect_anthropic_text(payload))


def _collect_response_text(payload: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if "text" in content:
                chunks.append(str(content["text"]))
    return "\n".join(chunks)


def _collect_openai_chat_text(payload: dict[str, Any]) -> str:
    chunks: list[str] = []
    for choice in payload.get("choices", []):
        message = choice.get("message") or {}
        if "content" in message:
            chunks.append(str(message["content"]))
    return "\n".join(chunks)


def _collect_anthropic_text(payload: dict[str, Any]) -> str:
    chunks: list[str] = []
    for content in payload.get("content", []):
        if content.get("type") == "text" and "text" in content:
            chunks.append(str(content["text"]))
    return "\n".join(chunks)


def openai_responses_text(settings: dict[str, Any], prompt: str, *, system: str = "Return strict JSON only.") -> str:
    api_key = settings.get("api_key")
    if not api_key:
        raise ProviderError("api_key is required for responses provider")
    base_url = str(settings.get("base_url") or "https://api.openai.com").rstrip("/")
    model = settings.get("model") or "gpt-5.5"
    timeout_seconds = int(settings.get("provider_timeout_seconds") or 120)
    body = {
        "model": model,
        "input": f"{system}\n\n{prompt}" if system else prompt,
        "reasoning": {"effort": settings.get("reasoning_effort") or "medium"},
        "max_output_tokens": int(settings.get("max_output_tokens") or 4096),
    }
    response = httpx.post(
        f"{base_url}/v1/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout_seconds,
    )
    if response.status_code >= 400:
        raise ProviderError(f"responses failed: {response.status_code} {response.text[:500]}")
    payload = response.json()
    return str(payload.get("output_text") or _collect_response_text(payload))


def openai_chat_text(settings: dict[str, Any], prompt: str, *, system: str = "Return strict JSON only.") -> str:
    api_key = settings.get("api_key")
    if not api_key:
        raise ProviderError("api_key is required for OpenAI chat-compatible provider")
    base_url = str(settings.get("base_url") or "https://api.openai.com").rstrip("/")
    model = settings.get("model") or "gpt-5.5"
    timeout_seconds = int(settings.get("provider_timeout_seconds") or 120)
    prompt_content = "Read this task from a JSON string. Decode Unicode escapes before following it.\nPrompt JSON string:\n" + json.dumps(prompt, ensure_ascii=True)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt_content},
        ],
        "max_tokens": int(settings.get("max_output_tokens") or 4096),
    }
    reasoning_effort = str(settings.get("reasoning_effort") or "").strip()
    if reasoning_effort and reasoning_effort not in {"none", "adaptive"}:
        body["reasoning"] = {"effort": reasoning_effort}
    response = httpx.post(
        f"{base_url}/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout_seconds,
    )
    if response.status_code >= 400:
        raise ProviderError(f"openai chat-compatible provider failed: {response.status_code} {response.text[:500]}")
    return _collect_openai_chat_text(response.json())


def anthropic_messages_text(settings: dict[str, Any], prompt: str, *, system: str = "Return strict JSON only.") -> str:
    api_key = settings.get("api_key")
    if not api_key:
        raise ProviderError("api_key is required for Claude provider")
    base_url = str(settings.get("base_url") or "https://api.anthropic.com").rstrip("/")
    model = settings.get("model") or "claude-sonnet-4-6"
    timeout_seconds = int(settings.get("provider_timeout_seconds") or 180)
    response = httpx.post(
        f"{base_url}/v1/messages",
        headers={
            "x-api-key": str(api_key),
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": int(settings.get("max_output_tokens") or 4096),
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=timeout_seconds,
    )
    if response.status_code >= 400:
        raise ProviderError(f"claude messages failed: {response.status_code} {response.text[:500]}")
    return _collect_anthropic_text(response.json())


def call_text(settings: dict[str, Any], prompt: str, *, provider_override: str | None = None, system: str = "Return strict JSON only.") -> str:
    provider = normalize_provider_name(provider_override or settings.get("provider"))
    if provider == "openai":
        return openai_responses_text(settings, prompt, system=system)
    if provider == "openai-chat":
        return openai_chat_text(settings, prompt, system=system)
    if provider == "anthropic":
        return anthropic_messages_text(settings, prompt, system=system)
    if provider == TEST_FAKE_PROVIDER:
        raise ProviderError("test fake provider cannot run semantic text generation")
    raise ProviderError(f"unsupported provider: {provider}")


def _image_data_url(image_path: Path) -> tuple[str, str, str]:
    media_type = mimetypes.guess_type(str(image_path))[0] or "image/png"
    data = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return media_type, data, f"data:{media_type};base64,{data}"


def openai_responses_image_text(settings: dict[str, Any], prompt: str, image_path: Path, *, system: str = "Return strict JSON only.") -> str:
    api_key = settings.get("api_key")
    if not api_key:
        raise ProviderError("api_key is required for image analysis")
    base_url = str(settings.get("base_url") or "https://api.openai.com").rstrip("/")
    model = settings.get("model") or "gpt-5.5"
    timeout_seconds = int(settings.get("provider_timeout_seconds") or 120)
    _, _, data_url = _image_data_url(image_path)
    body = {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": f"{system}\n\n{prompt}" if system else prompt},
                    {"type": "input_image", "image_url": data_url},
                ],
            }
        ],
        "reasoning": {"effort": settings.get("reasoning_effort") or "medium"},
        "max_output_tokens": int(settings.get("max_output_tokens") or 4096),
    }
    response = httpx.post(
        f"{base_url}/v1/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout_seconds,
    )
    if response.status_code >= 400:
        raise ProviderError(f"image analysis failed: {response.status_code} {response.text[:500]}")
    payload = response.json()
    return str(payload.get("output_text") or _collect_response_text(payload))


def openai_chat_image_text(settings: dict[str, Any], prompt: str, image_path: Path, *, system: str = "Return strict JSON only.") -> str:
    api_key = settings.get("api_key")
    if not api_key:
        raise ProviderError("api_key is required for image analysis")
    base_url = str(settings.get("base_url") or "https://api.openai.com").rstrip("/")
    model = settings.get("model") or "gpt-5.5"
    timeout_seconds = int(settings.get("provider_timeout_seconds") or 120)
    _, _, data_url = _image_data_url(image_path)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        "max_tokens": int(settings.get("max_output_tokens") or 4096),
    }
    reasoning_effort = str(settings.get("reasoning_effort") or "").strip()
    if reasoning_effort and reasoning_effort not in {"none", "adaptive"}:
        body["reasoning"] = {"effort": reasoning_effort}
    response = httpx.post(
        f"{base_url}/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout_seconds,
    )
    if response.status_code >= 400:
        raise ProviderError(f"image analysis failed: {response.status_code} {response.text[:500]}")
    return _collect_openai_chat_text(response.json())


def anthropic_messages_image_text(settings: dict[str, Any], prompt: str, image_path: Path, *, system: str = "Return strict JSON only.") -> str:
    api_key = settings.get("api_key")
    if not api_key:
        raise ProviderError("api_key is required for image analysis")
    base_url = str(settings.get("base_url") or "https://api.anthropic.com").rstrip("/")
    model = settings.get("model") or "claude-sonnet-4-6"
    timeout_seconds = int(settings.get("provider_timeout_seconds") or 180)
    media_type, data, _ = _image_data_url(image_path)
    response = httpx.post(
        f"{base_url}/v1/messages",
        headers={
            "x-api-key": str(api_key),
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": int(settings.get("max_output_tokens") or 4096),
            "system": system,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
                    ],
                }
            ],
        },
        timeout=timeout_seconds,
    )
    if response.status_code >= 400:
        raise ProviderError(f"image analysis failed: {response.status_code} {response.text[:500]}")
    return _collect_anthropic_text(response.json())


def call_image_text(settings: dict[str, Any], prompt: str, image_path: Path, *, provider_override: str | None = None, system: str = "Return strict JSON only.") -> str:
    provider = normalize_provider_name(provider_override or settings.get("provider"))
    if provider == "openai":
        return openai_responses_image_text(settings, prompt, image_path, system=system)
    if provider == "openai-chat":
        return openai_chat_image_text(settings, prompt, image_path, system=system)
    if provider == "anthropic":
        return anthropic_messages_image_text(settings, prompt, image_path, system=system)
    if provider == TEST_FAKE_PROVIDER:
        raise ProviderError("test fake provider cannot run image analysis")
    raise ProviderError(f"unsupported provider: {provider}")


def parse_jsonl_items(text: str) -> list[TranslationItem]:
    items: list[TranslationItem] = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line:
            continue
        if line.startswith("```"):
            continue
        payload = json.loads(line)
        items.append(TranslationItem(id=_normalize_translation_id(payload["id"]), translation=str(payload["translation"])))
    if not items:
        raise ProviderError("provider returned no JSONL translation rows")
    return items


async def translate_batch(
    rows: list[dict[str, Any]],
    settings: dict[str, Any],
    project_prompt: str,
    provider_override: str | None = None,
    protocol_override: str | None = None,
) -> list[TranslationItem]:
    provider = normalize_provider_name(provider_override or settings.get("provider"))
    _ = protocol_override
    project_prompt = manage_project_prompt_context(project_prompt, settings)
    if provider == TEST_FAKE_PROVIDER:
        return test_fake_translate_batch(rows, settings)
    if provider == "anthropic":
        return await anthropic_messages_translate_batch(rows, settings, project_prompt)
    if provider == "openai-chat":
        return await openai_chat_translate_batch(rows, settings, project_prompt)
    if provider == "openai":
        return await openai_responses_translate_batch(rows, settings, project_prompt)
    raise ProviderError(f"unsupported provider: {provider}")
