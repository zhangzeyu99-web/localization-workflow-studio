"""Program-owned templates for translating and reviewing code-heavy text."""
from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any


CJK_RE = re.compile(r"[\u3400-\u9fff]")
TECHNICAL_START_RE = re.compile(r"<(?=@\d+>|/?[A-Za-z])")
JSON_STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"')


@dataclass(frozen=True)
class TemplatePart:
    kind: str
    value: str


@dataclass(frozen=True)
class TranslationSlot:
    slot_key: str
    path: tuple[str | int, ...]
    part_index: int
    source: str
    prefix: str
    suffix: str
    context: str


@dataclass(frozen=True)
class ReviewSlot:
    slot_key: str
    path: tuple[str | int, ...]
    part_index: int
    source: str
    target: str
    target_prefix: str
    target_suffix: str
    source_context: str
    target_context: str


@dataclass
class ParsedTemplate:
    original_text: str
    root: object
    is_json: bool
    leaves: dict[tuple[str | int, ...], list[TemplatePart]]


def _technical_token(text: str, start: int) -> tuple[str, int]:
    if text.startswith("<@", start):
        end = text.find(">", start + 2)
        if end < 0:
            raise ValueError(f"unterminated placeholder at {start}")
        return text[start : end + 1], end + 1
    cursor = start + 1
    while cursor < len(text):
        if text.startswith("<@", cursor):
            inner_end = text.find(">", cursor + 2)
            if inner_end < 0:
                raise ValueError(f"unterminated nested placeholder at {cursor}")
            cursor = inner_end + 1
            continue
        if text[cursor] == ">":
            return text[start : cursor + 1], cursor + 1
        cursor += 1
    raise ValueError(f"unterminated tag at {start}")


def tokenize_template(text: str) -> list[TemplatePart]:
    parts: list[TemplatePart] = []
    cursor = 0
    while True:
        match = TECHNICAL_START_RE.search(text, cursor)
        if match is None:
            parts.append(TemplatePart("text", text[cursor:]))
            break
        start = match.start()
        parts.append(TemplatePart("text", text[cursor:start]))
        token, cursor = _technical_token(text, start)
        parts.append(TemplatePart("code", token))
    return parts


def technical_tokens(text: str) -> list[str]:
    return [part.value for part in tokenize_template(text) if part.kind == "code"]


def _shape(value: object) -> object:
    if isinstance(value, list):
        return [_shape(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _shape(item) for key, item in value.items()}
    return "str" if isinstance(value, str) else type(value).__name__


def parse_template(text: str) -> ParsedTemplate:
    is_json = False
    root: object = text
    stripped = text.strip()
    if stripped.startswith(("[", "{")):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, (list, dict)):
            root = parsed
            is_json = True
    leaves: dict[tuple[str | int, ...], list[TemplatePart]] = {}

    def collect(value: object, path: tuple[str | int, ...] = ()) -> None:
        if isinstance(value, list):
            for index, item in enumerate(value):
                collect(item, (*path, index))
            return
        if isinstance(value, dict):
            for key, item in value.items():
                collect(item, (*path, str(key)))
            return
        if isinstance(value, str):
            leaves[path] = tokenize_template(value)

    collect(root)
    return ParsedTemplate(text, root, is_json, leaves)


def _plain_context(parts: list[TemplatePart]) -> str:
    return "".join(part.value for part in parts if part.kind == "text").strip()


def translation_slots(template: ParsedTemplate) -> list[TranslationSlot]:
    slots: list[TranslationSlot] = []
    for path, parts in template.leaves.items():
        context = _plain_context(parts)
        for part_index, part in enumerate(parts):
            if part.kind != "text" or not CJK_RE.search(part.value):
                continue
            positions = [index for index, char in enumerate(part.value) if CJK_RE.match(char)]
            first = positions[0]
            last = positions[-1] + 1
            slots.append(
                TranslationSlot(
                    slot_key=f"{len(slots)}",
                    path=path,
                    part_index=part_index,
                    source=part.value[first:last],
                    prefix=part.value[:first],
                    suffix=part.value[last:],
                    context=context,
                )
            )
    return slots


def _assign(root: object, path: tuple[str | int, ...], value: str) -> object:
    if not path:
        return value
    node = root
    for key in path[:-1]:
        node = node[key]  # type: ignore[index]
    node[path[-1]] = value  # type: ignore[index]
    return root


def _json_string_entries(
    value: object,
    path: tuple[str | int, ...] = (),
) -> list[tuple[str, tuple[str | int, ...] | None, str]]:
    entries: list[tuple[str, tuple[str | int, ...] | None, str]] = []
    if isinstance(value, list):
        for index, item in enumerate(value):
            entries.extend(_json_string_entries(item, (*path, index)))
    elif isinstance(value, dict):
        for key, item in value.items():
            entries.append(("key", None, str(key)))
            entries.extend(_json_string_entries(item, (*path, str(key))))
    elif isinstance(value, str):
        entries.append(("value", path, value))
    return entries


def _render_json_original(
    template: ParsedTemplate,
    rendered_leaves: dict[tuple[str | int, ...], str],
) -> str:
    matches = list(JSON_STRING_RE.finditer(template.original_text))
    entries = _json_string_entries(template.root)
    if len(matches) != len(entries):
        raise ValueError("JSON string token count differs from parsed structure")
    chunks: list[str] = []
    cursor = 0
    for match, (kind, path, original_value) in zip(matches, entries, strict=True):
        if json.loads(match.group(0)) != original_value:
            raise ValueError("JSON string token order differs from parsed structure")
        chunks.append(template.original_text[cursor : match.start()])
        if kind == "value" and path is not None and rendered_leaves[path] != original_value:
            chunks.append(json.dumps(rendered_leaves[path], ensure_ascii=False))
        else:
            chunks.append(match.group(0))
        cursor = match.end()
    chunks.append(template.original_text[cursor:])
    return "".join(chunks)


def render_template(
    template: ParsedTemplate,
    replacements: dict[tuple[tuple[str | int, ...], int], str],
) -> str:
    root = deepcopy(template.root)
    rendered_leaves: dict[tuple[str | int, ...], str] = {}
    for path, parts in template.leaves.items():
        rendered = "".join(
            replacements.get((path, index), part.value)
            for index, part in enumerate(parts)
        )
        rendered_leaves[path] = rendered
        root = _assign(root, path, rendered)
    if template.is_json:
        result = _render_json_original(template, rendered_leaves)
        parsed_result = json.loads(result)
        if _shape(parsed_result) != _shape(template.root):
            raise ValueError("rebuilt JSON shape differs from source")
    else:
        result = str(root)
    if technical_tokens(result) != technical_tokens(template.original_text):
        raise ValueError("rebuilt technical token sequence differs from source")
    return result


def render_translations(
    template: ParsedTemplate,
    slots: list[TranslationSlot],
    values: dict[str, str],
) -> str:
    replacements = {
        (slot.path, slot.part_index): slot.prefix + values[slot.slot_key].strip() + slot.suffix
        for slot in slots
    }
    return render_template(template, replacements)


def aligned_review_slots(source_text: str, target_text: str) -> tuple[ParsedTemplate, list[ReviewSlot]]:
    source = parse_template(source_text)
    target = parse_template(target_text)
    if source.is_json != target.is_json or _shape(source.root) != _shape(target.root):
        raise ValueError("source and target JSON shapes differ")
    if set(source.leaves) != set(target.leaves):
        raise ValueError("source and target string paths differ")
    slots: list[ReviewSlot] = []
    for path, source_parts in source.leaves.items():
        target_parts = target.leaves[path]
        source_code = [part.value for part in source_parts if part.kind == "code"]
        target_code = [part.value for part in target_parts if part.kind == "code"]
        if source_code != target_code:
            raise ValueError("source and target technical token sequences differ")
        source_text_parts = [part for part in source_parts if part.kind == "text"]
        target_text_parts = [part for part in target_parts if part.kind == "text"]
        if len(source_text_parts) != len(target_text_parts):
            raise ValueError("source and target text slot counts differ")
        source_context = _plain_context(source_parts)
        target_context = _plain_context(target_parts)
        target_text_indexes = [index for index, part in enumerate(target_parts) if part.kind == "text"]
        for source_part, target_part, part_index in zip(
            source_text_parts, target_text_parts, target_text_indexes, strict=True
        ):
            if not CJK_RE.search(source_part.value) or not target_part.value.strip():
                continue
            left = len(target_part.value) - len(target_part.value.lstrip())
            right = len(target_part.value) - len(target_part.value.rstrip())
            core_end = len(target_part.value) - right if right else len(target_part.value)
            slots.append(
                ReviewSlot(
                    slot_key=f"{len(slots)}",
                    path=path,
                    part_index=part_index,
                    source=source_part.value.strip(),
                    target=target_part.value[left:core_end],
                    target_prefix=target_part.value[:left],
                    target_suffix=target_part.value[core_end:],
                    source_context=source_context,
                    target_context=target_context,
                )
            )
    return target, slots


def render_reviewed_target(
    target_template: ParsedTemplate,
    slots: list[ReviewSlot],
    values: dict[str, str],
) -> str:
    replacements = {
        (slot.path, slot.part_index): slot.target_prefix + values[slot.slot_key].strip() + slot.target_suffix
        for slot in slots
    }
    return render_template(target_template, replacements)


def should_use_template(row: dict[str, Any]) -> bool:
    if str(row.get("source_mode") or "cn").lower() != "cn":
        return False
    source = str(row.get("translation_source") or row.get("cn") or "")
    if not CJK_RE.search(source):
        return False
    parsed = parse_template(source)
    return parsed.is_json or len(technical_tokens(source)) >= 3
