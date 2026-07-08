"""Announcement term workbook loading and term-hit extraction.

Implementation module split out of utils/announcement_docx_harness.py. Import
these symbols through utils.announcement_docx_harness to keep the public
surface stable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from utils.announcement_docx_common import (
    CANONICAL_LANGUAGE_HEADER,
    _CJK_RE,
    _clean_cell,
    _language_code_for_header,
)

_ANNOUNCEMENT_PLACEHOLDER_RE = re.compile(r"<@\d+>|\$\{\d+\}|%[sdif]|\{[^{}]+\}|<[^>]+>|\\n")
_ANNOUNCEMENT_SENTENCE_PUNCTUATION = set("，。！？；：、,.?!;:")
_LOW_VALUE_ANNOUNCEMENT_TERMS = {
    "好的",
    "游戏",
    "时间",
    "小时",
    "完成",
    "发放",
    "领取",
    "获得",
    "获取",
    "更新",
    "进入",
    "点击",
    "下载",
    "界面",
    "弹窗",
    "邮件",
    "活动",
    "系统",
    "玩法",
    "服务器",
    "维护",
    "补偿",
    "内容",
    "任务",
    "奖励",
    "开启",
    "开放",
    "修复",
    "新增",
    "部分",
    "所有",
    "普通",
    "使用",
    "问题",
    "确认",
    "取消",
    "返回",
    "查看",
    "选择",
    "购买",
    "前往",
    "本次",
    "当前",
    "公告",
    "进入游戏",
    "开始游戏",
}
_LOW_VALUE_ANNOUNCEMENT_PREFIXES = (
    "使用后",
    "用于",
    "可",
    "将",
    "已",
    "未",
    "请",
    "点击",
    "前往",
    "打开",
    "关闭",
    "获得",
    "完成",
    "通关",
    "达到",
    "活动期间",
    "当前",
    "本期",
    "每日",
    "成功",
    "失败",
    "进入",
    "开始",
    "返回",
    "查看",
    "选择",
)
_LOW_VALUE_ANNOUNCEMENT_SUBSTRINGS = (
    "是否",
    "不足",
    "尚未",
    "暂无",
    "已达",
    "未领取",
    "已领取",
    "补发",
    "异常",
    "排行奖励",
    "奖励邮件",
    "正在",
    "倒计时",
)
_TERM_NOUN_SUFFIXES = (
    "活动",
    "系统",
    "玩法",
    "副本",
    "战场",
    "商店",
    "商城",
    "公会",
    "英雄",
    "角色",
    "皮肤",
    "碎片",
    "宝箱",
    "礼包",
    "月卡",
    "通行证",
    "圣器",
    "遗物",
    "机关",
    "装备",
    "材料",
    "水晶",
    "金币",
    "硬币",
    "积分",
    "图鉴",
    "技能",
)


@dataclass(frozen=True)
class LanguageSpec:
    header: str
    code: str
    column_index: int


@dataclass(frozen=True)
class TermEntry:
    source: str
    target: str
    term_id: str = ""


@dataclass(frozen=True)
class AnnouncementTerms:
    path: Path
    languages: list[LanguageSpec]
    by_language: dict[str, dict[str, TermEntry]]


def load_announcement_terms(path: str | Path) -> AnnouncementTerms:
    path = Path(path)
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.active
        languages = _language_specs_from_headers(
            [str(ws.cell(1, col).value or "").strip() for col in range(1, ws.max_column + 1)]
        )
        by_language: dict[str, dict[str, TermEntry]] = {}
        for spec in languages:
            by_language[spec.header] = {}

        for row in range(2, ws.max_row + 1):
            term_id = _clean_cell(ws.cell(row, 1).value)
            source = _clean_cell(ws.cell(row, 2).value)
            if not source:
                continue
            for spec in languages:
                target = _clean_cell(ws.cell(row, spec.column_index).value)
                if target:
                    by_language[spec.header][source] = TermEntry(source=source, target=target, term_id=term_id)
    finally:
        wb.close()
    return AnnouncementTerms(path=path, languages=languages, by_language=by_language)


def _read_announcement_language_specs(path: Path) -> list[LanguageSpec]:
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.active
        headers = [str(ws.cell(1, col).value or "").strip() for col in range(1, ws.max_column + 1)]
        return _language_specs_from_headers(headers)
    finally:
        wb.close()


def _language_specs_from_headers(headers: list[str]) -> list[LanguageSpec]:
    languages: list[LanguageSpec] = []
    seen_codes: set[str] = set()
    for col in range(3, len(headers) + 1):
        input_header = headers[col - 1]
        code = _language_code_for_header(input_header)
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        header = CANONICAL_LANGUAGE_HEADER[code]
        languages.append(LanguageSpec(header=header, code=code, column_index=col))
    return languages


def _find_term_hits(source: str, terms: AnnouncementTerms) -> list[dict[str, Any]]:
    all_sources = {
        term
        for lang_terms in terms.by_language.values()
        for term in lang_terms
        if len(term) >= 2 and not _is_low_value_announcement_term(term) and _term_occurs(source, term)
    }
    selected: list[str] = []
    for term in sorted(all_sources, key=len, reverse=True):
        if any(term in longer for longer in selected):
            continue
        selected.append(term)

    hits: list[dict[str, Any]] = []
    for source_term in selected:
        targets = {}
        for spec in terms.languages:
            entry = terms.by_language.get(spec.header, {}).get(source_term)
            if entry:
                targets[spec.header] = entry.target
        if targets:
            hits.append({"source": source_term, "targets": targets})
    return hits


def _is_low_value_announcement_term(source: str) -> bool:
    text = str(source or "").strip()
    if not text:
        return True
    if text in _LOW_VALUE_ANNOUNCEMENT_TERMS:
        return True
    if not _CJK_RE.search(text):
        return True
    if len(text) <= 1:
        return True
    if _ANNOUNCEMENT_PLACEHOLDER_RE.search(text):
        return True
    if any(char.isdigit() for char in text) and not any(text.endswith(suffix) for suffix in _TERM_NOUN_SUFFIXES):
        return True
    cjk_len = sum(1 for char in text if "\u3400" <= char <= "\u9fff")
    if cjk_len <= 2 and text.endswith(("级", "次", "个", "点", "日", "月")):
        return True
    if any(mark in text for mark in _ANNOUNCEMENT_SENTENCE_PUNCTUATION) and cjk_len > 4:
        return True
    if any(text.startswith(prefix) for prefix in _LOW_VALUE_ANNOUNCEMENT_PREFIXES) and cjk_len > 4:
        return True
    if any(part in text for part in _LOW_VALUE_ANNOUNCEMENT_SUBSTRINGS) and cjk_len > 5:
        return True
    if cjk_len > 10 and not any(text.endswith(suffix) for suffix in _TERM_NOUN_SUFFIXES):
        return True
    return False


def _term_occurs(source: str, term: str) -> bool:
    start = 0
    while True:
        index = source.find(term, start)
        if index < 0:
            return False
        before = source[index - 1] if index > 0 else ""
        after_index = index + len(term)
        after = source[after_index] if after_index < len(source) else ""
        if term[0].isdigit() and before.isdigit():
            start = index + 1
            continue
        if term[-1].isdigit() and after.isdigit():
            start = index + 1
            continue
        return True
