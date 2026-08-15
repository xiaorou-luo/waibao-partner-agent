"""轻量工具：联网搜索、读文件、列目录。

- 联网搜索：使用 Tavily（OpenAI 生态常用搜索 API），需要设置 TAVILY_API_KEY
  （https://tavily.com 有免费额度）；未配置时给出友好提示。
- 读文件/列目录：只读，且限制在允许的根目录内，避免越界。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path


def _allowed_root() -> Path:
    """允许读取/列目录的根目录，默认本项目目录，可用 WAIBao_ALLOWED_ROOT 覆盖。"""
    default = Path(__file__).resolve().parent.parent
    return Path(os.environ.get("WAIBao_ALLOWED_ROOT", str(default))).resolve()


def web_search(query: str, max_results: int = 5) -> str:
    """联网搜索，返回带摘要的结果文本。"""
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        return "（未配置 TAVILY_API_KEY，无法联网搜索。到 tavily.com 申请免费 Key 后设置该环境变量即可。）"
    payload = {"query": query, "max_results": max_results, "search_depth": "basic"}
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return f"（搜索失败：HTTP {exc.code} {exc.read().decode('utf-8','replace')[:200]}）"
    except Exception as exc:  # noqa: BLE001
        return f"（搜索失败：{exc}）"

    lines: list[str] = []
    answer = data.get("answer")
    if answer:
        lines.append(f"AI 摘要：{answer}")
    for r in data.get("results", [])[:max_results]:
        lines.append(f"- {r.get('title','')}\n  {r.get('url','')}\n  {r.get('content','')[:300]}")
    return "\n\n".join(lines) if lines else "（无结果）"


def read_file(path: str) -> str:
    """只读读取一个文本文件，限制在允许根目录内。"""
    base = _allowed_root()
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    p = p.resolve()
    try:
        p.relative_to(base)
    except ValueError:
        return f"（出于安全，仅允许读取 {base} 目录内的文件）"
    if not p.exists():
        return f"（文件不存在：{p}）"
    if p.is_dir():
        return f"（{p} 是目录，请用「列出文件」）"
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return f"（读取失败：{exc}）"


def list_dir(path: str = ".") -> str:
    """列出目录内容（只读）。"""
    base = _allowed_root()
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    p = p.resolve()
    try:
        p.relative_to(base)
    except ValueError:
        return f"（出于安全，仅允许访问 {base} 目录）"
    if not p.exists() or not p.is_dir():
        return f"（目录不存在：{p}）"
    names = sorted(str(x.name) for x in p.iterdir())
    return "\n".join(f"- {n}" for n in names) if names else "（空目录）"

