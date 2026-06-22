from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def artifact_download_url(project_id: str, artifact_id: str) -> str:
    return f"/api/projects/{project_id}/artifacts/{artifact_id}/download"


def delivery_file_download_url(project_id: str, filename: str) -> str:
    return f"/api/projects/{project_id}/delivery/{filename}"


def delivery_item_download_url(project_id: str, item: dict[str, Any]) -> str:
    if item.get("artifact_id"):
        return artifact_download_url(project_id, str(item["artifact_id"]))
    if item.get("path"):
        return delivery_file_download_url(project_id, str(item.get("filename") or ""))
    return ""


def attach_delivery_item_downloads(project_id: str, items: Iterable[dict[str, Any]]) -> None:
    for item in items:
        if item.get("download_url"):
            continue
        item["download_url"] = delivery_item_download_url(project_id, item)
