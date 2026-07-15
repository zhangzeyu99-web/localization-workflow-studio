"""Project membership management API (A2 batch 2).

Boundary: membership only decides *visibility* of a project for ops/member
roles -- admins always see every project regardless of this table (see
``authz.require_project_access``). Every route below carries ``project_id``
in its path, so the centrally-registered ``route_capabilities`` gate already
enforces both the required capability (``PROJECT_READ`` to view,
``PROJECT_MANAGE`` to add/remove) *and* that the caller is themselves a
member of that project (or admin) before the handler body ever runs -- this
is exactly the plan's "运营只能管理自己成员项目的成员" rule, and it comes for
free from the same table-driven gate every other route uses, not from
anything bespoke in this file.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from .. import auth, db, operator_context
from ..config import DATA_ROOT
from ..schemas import ProjectMemberAddRequest

router = APIRouter()


def _public_member(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": row["project_id"],
        "user_id": row["user_id"],
        "username": row["username"],
        "display_name": row.get("display_name") or "",
        "role": row["role"],
        "status": row["status"],
        "added_by": row.get("added_by") or "",
        "created_at": row.get("created_at"),
    }


@router.get("/api/projects/{project_id}/members")
def list_members(project_id: str) -> list[dict[str, Any]]:
    try:
        db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    return [_public_member(row) for row in db.list_project_members(project_id)]


@router.post("/api/projects/{project_id}/members")
def add_member(project_id: str, payload: ProjectMemberAddRequest) -> dict[str, Any]:
    try:
        db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    try:
        target = db.get_user(payload.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="user not found") from exc
    actor = auth.current_user() or {}
    db.add_project_member(project_id, target["id"], added_by=str(actor.get("id") or ""))
    operator_context.record_operator_audit(
        DATA_ROOT, "add_project_member", {"project_id": project_id, "username": target["username"]}
    )
    member = next(
        (row for row in db.list_project_members(project_id) if row["user_id"] == target["id"]),
        None,
    )
    return _public_member(member) if member else {"project_id": project_id, "user_id": target["id"]}


@router.delete("/api/projects/{project_id}/members/{user_id}")
def remove_member(project_id: str, user_id: str) -> dict[str, bool]:
    try:
        db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    removed = db.remove_project_member(project_id, user_id)
    if removed:
        operator_context.record_operator_audit(
            DATA_ROOT, "remove_project_member", {"project_id": project_id, "user_id": user_id}
        )
    return {"deleted": removed}
