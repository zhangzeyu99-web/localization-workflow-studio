"""Shared constants: paths, versions, regexes, headers, and term sets."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CURATED_RULES = REPO_ROOT / "data" / "experience" / "curated_terms.json"
DEFAULT_OBSERVATIONS_STORE = REPO_ROOT / "data" / "experience" / "observed_terms.json"
DEFAULT_LEGACY_EXPERIENCE_STORE = REPO_ROOT / "data" / "experience" / "term_memory.json"
CURATED_VERSION = 1
OBSERVATION_VERSION = 1

SENTENCE_PUNCT_RE = re.compile(r"[，。！？；：,.!?;:\n]")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
PLACEHOLDER_RE = re.compile(r"\{\d+\}|%[sd]|\\n")
BRACKET_TAG_RE = re.compile(r"\[[^\]]*\]")
HTML_TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
NON_TERM_RE = re.compile(r"^[\W_]+$|^[IVXⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+$")
CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")
EN_COMPARE_RE = re.compile(r"[^a-z0-9+ ]+")
EN_WORD_RE = re.compile(r"[a-z0-9+]+")
NUMBERED_TITLE_RE = re.compile(r"^\s*(?:[0-9]+|[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341]+)\s*[\u3001.．\s-]+")
HEADER_SCAN_LIMIT = 50

AUTO_ID_HEADERS = ["ID", "id", "\u7d22\u5f15ID", "\u552f\u4e00\u6807\u8bc6ID"]
AUTO_SOURCE_HEADERS = ["CN", "cn", "zh", "source", "Chinese", "\u4e2d\u6587", "\u7b80\u4f53\u4e2d\u6587", "ori_string"]
AUTO_TARGET_HEADERS = ["EN", "en", "target", "translation", "English", "\u82f1\u6587", "\u82f1\u8bed", "\u5185\u5bb9", "text"]
LOW_VALUE_ANNOUNCEMENT_TERMS = {
    "\u73a9\u5bb6",
    "\u6d3b\u52a8",
    "\u4e16\u754c",
    "\u8d2d\u4e70",
    "\u53d1\u9001",
    "\u67e5\u770b",
    "\u83b7\u5f97",
    "\u5956\u52b1",
    "\u9884\u544a",
    "\u7cfb\u7edf",
}
AI_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
AI_SUPPLEMENT_SCHEMA_VERSION = 1
AI_SUPPLEMENT_EVIDENCE_LIMIT = 80
AI_SUPPLEMENT_EVIDENCE_PER_TERM = 3
DEFAULT_AI_SUPPLEMENT_MODEL = "gpt-4.1-mini"
DEFAULT_OPENAI_RESPONSES_API_URL = "https://api.openai.com/v1/responses"
CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
QUOTED_TERM_RE = re.compile(r"[《「『“\"']([^《》「」『』“”\"']{2,20})[》」』”\"']")

RARITY_TERMS = {
    "普通",
    "精良",
    "精英",
    "卓越",
    "史诗",
    "传说",
    "神话",
    "高级",
}
RESOURCE_TERMS = {
    "钻石",
    "石油",
    "体力",
    "宝石",
    "积分",
    "碎片",
    "材料",
    "芯片",
    "能量",
    "金币",
    "经验",
    "奖励",
    "礼包",
}
STAT_TERMS = {
    "攻击",
    "攻击力",
    "防御",
    "生命",
    "伤害",
    "伤害+",
    "暴击",
    "暴击伤害",
    "闪电",
    "火焰",
    "冰霜",
    "物理",
    "闪电伤害",
    "火焰伤害",
    "冰霜伤害",
    "物理伤害",
    "能量伤害",
}
ACTION_TERMS = {
    "获得",
    "获取",
    "领取",
    "使用",
    "合成",
    "升级",
    "强化",
    "突破",
    "升星",
    "激活",
    "解锁",
    "购买",
    "报名",
    "兑换",
    "刷新",
    "前往",
    "开始",
    "加入",
    "退出",
    "上阵",
    "建造",
    "邀请",
    "重置",
    "探索",
    "挑战",
}
SYSTEM_TERMS = {
    "公会",
    "竞技场",
    "战令",
    "签到",
    "商城",
    "商店",
    "背包",
    "排行",
    "排行榜",
    "活动",
    "防御塔",
    "兵营",
    "基地",
    "据点",
    "任务",
}
OBJECT_TERMS = {
    "英雄",
    "技能",
    "装备",
    "建筑",
    "武器",
    "士兵",
    "坐骑",
    "收藏品",
    "头像",
    "好友",
    "道具",
}
STATUS_TERMS = {
    "当前",
    "暂无",
    "不足",
    "已满",
    "失败",
    "可领取",
    "拥有",
    "最大",
    "剩余",
    "排名",
    "段位",
}

HIGH_CONFUSION_TERMS = (
    RARITY_TERMS
    | RESOURCE_TERMS
    | ACTION_TERMS
    | STATUS_TERMS
    | {
        "战力",
        "品质",
        "等级",
        "积分",
        "攻击",
        "觉醒",
        "奖励",
        "选择",
        "强化",
        "合成",
        "突破",
        "推荐",
    }
)

PROJECT_SIGNAL_GROUPS = {
    "合成/经营": {
        "合成",
        "订单",
        "生产",
        "生产机",
        "生产机器",
        "生成器",
        "仓库",
        "菜品",
        "烹饪",
        "顾客",
        "Merge",
    },
    "花店/装修": {
        "花店",
        "花束",
        "鲜花",
        "玫瑰",
        "百合",
        "装饰",
        "装修",
        "修复",
        "翻新",
        "花园",
        "Florist",
    },
    "休闲/女性向": {
        "女性向",
        "恋爱",
        "恋综",
        "都市",
        "时尚",
        "可爱",
        "漂亮",
        "温馨",
        "甜",
        "咖啡",
        "甜品",
        "裙",
        "珠宝",
        "约会",
        "浪漫",
        "美女",
        "小姐",
        "romance",
        "fashion",
        "cozy",
        "cute",
    },
    "战斗/RPG养成": {
        "战斗",
        "攻击",
        "防御",
        "生命",
        "伤害",
        "暴击",
        "技能",
        "英雄",
        "装备",
        "武器",
        "首领",
        "BOSS",
        "怪物",
        "关卡",
        "挑战",
    },
    "基地/建筑经营": {
        "基地",
        "建筑",
        "兵营",
        "防御塔",
        "建造",
        "升级",
        "营地",
        "总部",
        "据点",
        "采集",
        "生产",
    },
    "活动/商业化": {
        "活动",
        "签到",
        "战令",
        "礼包",
        "充值",
        "商店",
        "商城",
        "购买",
        "限时",
        "奖励",
        "抽奖",
        "召唤",
    },
    "社交/公会竞争": {
        "公会",
        "联盟",
        "好友",
        "排行榜",
        "排名",
        "竞技场",
        "聊天",
        "邀请",
        "成员",
        "队伍",
    },
    "飞行/射击题材": {
        "飞机",
        "战机",
        "飞行员",
        "机库",
        "导弹",
        "空袭",
        "射击",
        "僚机",
        "弹幕",
        "aircraft",
        "fighter",
        "jet",
        "plane",
        "missile",
        "shooter",
    },
    "末日/生存题材": {
        "幸存者",
        "僵尸",
        "末日",
        "避难所",
        "感染",
        "生存",
        "废土",
        "救援",
        "survival",
        "zombie",
        "wasteland",
        "shelter",
    },
    "剧情/叙事": {
        "剧情",
        "章节",
        "对话",
        "故事",
        "任务",
        "探索",
        "冒险",
        "线索",
        "选择",
        "先生",
        "老板",
        "小姐",
        "等等",
        "拜托",
        "story",
        "dialogue",
        "chapter",
    },
}

TEXT_MATERIAL_EXTENSIONS = {".txt", ".md", ".markdown", ".json"}
TABLE_MATERIAL_EXTENSIONS = {".xlsx", ".xlsm"}
DELIMITED_MATERIAL_EXTENSIONS = {".csv", ".tsv"}
IMAGE_MATERIAL_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
DOCX_MATERIAL_EXTENSIONS = {".docx"}

CATEGORY_LABELS = {
    "rarity": "稀有度/品质",
    "resource": "资源/货币/奖励",
    "stat": "战斗属性/数值",
    "action": "UI操作动词",
    "system": "系统/玩法名",
    "object": "角色/装备/对象",
    "status": "状态/进度",
    "other": "其他",
}
