from __future__ import annotations

from pathlib import Path

from app.workflow.announcement_segments import _txt_announcement_segments, _write_quick_text_output


def _write_gb18030(path: Path, text: str) -> None:
    path.write_bytes(text.encode("gb18030"))


def test_txt_announcement_segments_accepts_gb18030(tmp_path: Path) -> None:
    source_path = tmp_path / "0729版更.txt"
    _write_gb18030(source_path, "版本更新公告：活动开启！\n奖励内容：蘑菇、金币、礼包。\n")

    segments = _txt_announcement_segments(source_path)

    assert [segment["source"] for segment in segments] == [
        "版本更新公告：活动开启！",
        "奖励内容：蘑菇、金币、礼包。",
    ]


def test_quick_text_output_accepts_gb18030_source(tmp_path: Path) -> None:
    source_path = tmp_path / "0729版更.txt"
    _write_gb18030(source_path, "第一行\n\n第二行\n")
    segments = _txt_announcement_segments(source_path)
    translated_rows = [
        {"id": segments[0]["id"], "translation": "First line"},
        {"id": segments[1]["id"], "translation": "Second line"},
    ]

    output_path = _write_quick_text_output(source_path, translated_rows, "en", tmp_path)

    assert output_path.read_text(encoding="utf-8") == "First line\n\nSecond line\n"
