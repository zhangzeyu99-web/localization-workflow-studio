from __future__ import annotations

import re
from typing import Any

ANNOUNCEMENT_STEP = {
    "source": 1,
    "constraints": 2,
    "languages": 3,
    "terms": 4,
    "lookup": 5,
    "prepare": 6,
    "translate": 7,
    "apply": 8,
    "deliver": 9,
}


def _count_lookup_hits(text: str, needle: str) -> tuple[int, int]:
    if not needle:
        return (0, -1)
    count = 0
    first = -1
    start = 0
    while True:
        index = text.find(needle, start)
        if index < 0:
            break
        if first < 0:
            first = index
        count += 1
        start = index + max(1, len(needle))
    return (count, first)


def _suppress_overlapping_lookup_hits(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    spans: list[tuple[int, int]] = []
    for row in sorted(rows, key=lambda item: (int(item.get("first_position") or 0), -len(str(item.get("source") or "")), str(item.get("source") or ""))):
        start = int(row.get("first_position") or 0)
        end = start + len(str(row.get("source") or ""))
        if any(start < existing_end and end > existing_start for existing_start, existing_end in spans):
            continue
        accepted.append(row)
        spans.append((start, end))
    return accepted


_CJK_ANNOUNCEMENT_TERM_RE = re.compile(r"[\u3400-\u9fff]")
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
    "技能",
    "战斗",
    "召唤",
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


def _is_low_value_announcement_term(source: str) -> bool:
    text = str(source or "").strip()
    if not text:
        return True
    if text in _LOW_VALUE_ANNOUNCEMENT_TERMS:
        return True
    if not _CJK_ANNOUNCEMENT_TERM_RE.search(text):
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


def _announcement_term_occurs(source_text: str, term: str) -> tuple[int, int]:
    if _is_low_value_announcement_term(term):
        return (0, -1)
    return _count_lookup_hits(source_text, term)


def _rank_translation_lookup_source(source_type: str) -> int:
    priority = {
        "qa_passed": 0,
        "qa_final": 0,
        "manual": 1,
        "imported": 2,
        "archive": 2,
        "translation_archive": 2,
        "delivered_with_issues": 2,
    }
    return priority.get(str(source_type or "").strip().lower(), 3)


def _announcement_task_metadata(task: dict[str, Any]) -> dict[str, Any]:
    metadata = task.get("metadata")
    return dict(metadata) if isinstance(metadata, dict) else {}
