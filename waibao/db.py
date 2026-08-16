"""Supabase 账号系统与云端持久化（零第三方依赖，走 REST API）。

提供：邮箱注册/登录、按用户下载/上传个人数据。
需要在环境变量或 Streamlit Secrets 中配置：
  SUPABASE_URL       例如 https://xxxx.supabase.co
  SUPABASE_ANON_KEY  项目的 anon public key

数据模型：每个用户一行（public.user_data），`files` 字段是 JSONB，
形如 {"long_term_memory.json": "...", "conversation_history.json": "..."}。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


# 需要同步的个人数据文件（相对 storage_dir）
SYNC_FILES = (
    "long_term_memory.json",
    "episodic_memory.json",
    "evolution_state.json",
    "conversation_history.json",
    "conversation_summary.txt",
    "conversation_sessions.json",
    "learning_log.json",
    "portrait.json",
    "thoughts.json",
)


def _cfg() -> tuple[str, str]:
    url = (os.environ.get("SUPABASE_URL", "") or "").rstrip("/")
    key = (os.environ.get("SUPABASE_ANON_KEY", "") or "").strip()
    return url, key


def configured() -> bool:
    url, key = _cfg()
    return bool(url and key)


def _headers(token: str = "") -> dict[str, str]:
    _, key = _cfg()
    headers = {"apikey": key, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _parse_error(body: str) -> str:
    try:
        data = json.loads(body)
        return (
            data.get("msg")
            or data.get("message")
            or data.get("error_description")
            or data.get("error")
            or body[:200]
        )
    except Exception:
        return body[:200]


def _post(path: str, payload: dict, token: str = "") -> dict:
    url, _ = _cfg()
    req = urllib.request.Request(
        f"{url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(token),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_parse_error(exc.read().decode("utf-8", "replace"))) from exc


def sign_up(email: str, password: str) -> dict:
    """注册新账号。返回 {ok, user_id, access_token, email_confirmed, error}。"""
    try:
        data = _post(
            "/auth/v1/signup",
            {"email": email.strip(), "password": password},
        )
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"无法连接 Supabase：{exc}"}
    user = data.get("user", {}) or {}
    return {
        "ok": True,
        "user_id": user.get("id", ""),
        "access_token": data.get("access_token", ""),
        "refresh_token": data.get("refresh_token", ""),
        "email_confirmed": bool(user.get("email_confirmed_at") or user.get("confirmed_at")),
    }


def sign_in(email: str, password: str) -> dict:
    """登录。返回 {ok, user_id, access_token, refresh_token, error}。"""
    try:
        data = _post(
            "/auth/v1/token?grant_type=password",
            {"email": email.strip(), "password": password},
        )
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"无法连接 Supabase：{exc}"}
    user = data.get("user", {}) or {}
    return {
        "ok": True,
        "user_id": user.get("id", ""),
        "access_token": data.get("access_token", ""),
        "refresh_token": data.get("refresh_token", ""),
    }


def reset_password(email: str) -> dict:
    """发送密码重置邮件。返回 {ok, error}。"""
    url, _ = _cfg()
    req = urllib.request.Request(
        f"{url}/auth/v1/recover",
        data=json.dumps({"email": email.strip()}).encode("utf-8"),
        headers=_headers(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        return {"ok": True}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": _parse_error(exc.read().decode("utf-8", "replace"))}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"无法连接 Supabase：{exc}"}


def update_password(access_token: str, new_password: str) -> dict:
    """用密码重置邮件里的 token 设置新密码。返回 {ok, error}。"""
    url, _ = _cfg()
    req = urllib.request.Request(
        f"{url}/auth/v1/user",
        data=json.dumps({"password": new_password}).encode("utf-8"),
        headers=_headers(access_token),
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        return {"ok": True}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": _parse_error(exc.read().decode("utf-8", "replace"))}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"无法连接 Supabase：{exc}"}


def _rest(
    method: str,
    path: str,
    token: str,
    payload: dict | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict | list:
    url, _ = _cfg()
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = _headers(token)
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(
        f"{url}/rest/v1/{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_parse_error(exc.read().decode("utf-8", "replace"))) from exc


def download_user_data(user_id: str, token: str, storage_dir: str | Path) -> None:
    """把该用户的数据从云端下载到本地 storage_dir。"""
    q = urllib.parse.quote(f"user_id=eq.{user_id}")
    rows = _rest("GET", f"user_data?{q}&select=files", token)
    files = rows[0].get("files") if isinstance(rows, list) and rows else {}
    files = files or {}
    base = Path(storage_dir)
    base.mkdir(parents=True, exist_ok=True)
    for name in SYNC_FILES:
        if name in files:
            (base / name).write_text(files[name], encoding="utf-8")


def upload_user_data(user_id: str, token: str, storage_dir: str | Path) -> None:
    """把本地 storage_dir 的个人数据上传到云端。"""
    base = Path(storage_dir)
    files: dict[str, str] = {}
    for name in SYNC_FILES:
        p = base / name
        if p.exists():
            files[name] = p.read_text(encoding="utf-8")
    _rest(
        "POST",
        "user_data",
        token,
        payload={"user_id": user_id, "files": files},
        extra_headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
    )


def clear_user_data(user_id: str, token: str) -> None:
    """删除该用户的全部云端数据（用于「重置全部记忆」）。"""
    q = urllib.parse.quote(f"user_id=eq.{user_id}")
    _rest("DELETE", f"user_data?{q}", token)
