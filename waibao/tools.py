"""轻量工具：联网搜索、读文件、列目录。

- 联网搜索：使用 Tavily（OpenAI 生态常用搜索 API），需要设置 TAVILY_API_KEY
  （https://tavily.com 有免费额度）；未配置时给出友好提示。
- 读文件/列目录：只读，且限制在允许的根目录内，避免越界。
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path


def _allowed_root() -> Path:
    """允许读取/列目录的根目录，默认本项目目录，可用 WAIBao_ALLOWED_ROOT 覆盖。"""
    default = Path(__file__).resolve().parent.parent
    return Path(os.environ.get("WAIBao_ALLOWED_ROOT", str(default))).resolve()


def web_search_structured(query: str, max_results: int = 5) -> dict:
    """联网搜索，返回结构化结果 {ok, message, answer, results:[{title,url,content}]}。"""
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        return {
            "ok": False,
            "message": "（未配置 TAVILY_API_KEY，无法联网搜索。到 tavily.com 申请免费 Key 后设置该环境变量即可。）",
            "answer": "",
            "results": [],
        }
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
        return {"ok": False, "message": f"（搜索失败：HTTP {exc.code} {exc.read().decode('utf-8','replace')[:200]}）", "answer": "", "results": []}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"（搜索失败：{exc}）", "answer": "", "results": []}
    results = [
        {"title": r.get("title", ""), "url": r.get("url", ""), "content": (r.get("content") or "")[:300]}
        for r in data.get("results", [])[:max_results]
    ]
    return {"ok": True, "message": "", "answer": data.get("answer") or "", "results": results}


def web_search(query: str, max_results: int = 5) -> str:
    """联网搜索，返回带摘要的结果文本（兼容旧调用）。"""
    r = web_search_structured(query, max_results)
    if not r["ok"]:
        return r["message"]
    lines: list[str] = []
    if r["answer"]:
        lines.append(f"AI 摘要：{r['answer']}")
    for it in r["results"]:
        lines.append(f"- {it['title']}\n  {it['url']}\n  {it['content']}")
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


# ---- 新增：文件搜索 / 内容搜索 / 受控执行命令 -------------------------

_SKIP_DIRS = {
    "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".git",
    ".svn", ".hg", ".idea", ".vscode", ".next", ".nuxt", "target",
    "Library", "Applications", "System", "Volumes", "cores",
    ".Trash", ".Spotlight-V100", ".fseventsd", ".DocumentRevisions-V100",
    ".TemporaryItems",
}


def _skip_dir(name: str) -> bool:
    """搜索时跳过隐藏目录、依赖缓存、系统大目录，避免误扫和过慢。"""
    return name.startswith(".") or name in _SKIP_DIRS


def allowed_root_description() -> str:
    """返回当前允许访问的根目录（供界面展示）。"""
    return str(_allowed_root())


def search_files(query: str, limit: int = 50) -> str:
    """在允许根目录内按文件名/路径搜索（只读）。"""
    base = _allowed_root()
    q = query.strip().lower()
    if not q:
        return "（请提供要搜索的文件名关键词，例如：搜索文件 报告）"
    hits: list[str] = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not _skip_dir(d)]
        for name in files:
            if q in name.lower():
                hits.append(str(Path(root) / name))
                if len(hits) >= limit:
                    break
        if len(hits) >= limit:
            break
    if not hits:
        return f"（在 {base} 内没有找到文件名包含「{query}」的文件）"
    return "找到 " + str(len(hits)) + " 个文件：\n" + "\n".join(f"- {h}" for h in hits)


def search_content(query: str, limit: int = 30) -> str:
    """在允许根目录内搜索文本内容（只读，跳过二进制和大文件）。"""
    base = _allowed_root()
    q = query.strip()
    if not q:
        return "（请提供要搜索的内容关键词，例如：搜索内容 预算）"
    hits: list[str] = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not _skip_dir(d)]
        for name in files:
            p = Path(root) / name
            try:
                if p.stat().st_size > 2_000_000:
                    continue
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if q in text:
                hits.append(str(p))
                if len(hits) >= limit:
                    break
        if len(hits) >= limit:
            break
    if not hits:
        return f"（在 {base} 内没有找到包含「{query}」的文件）"
    return "找到 " + str(len(hits)) + " 个文件包含「" + query + "」：\n" + "\n".join(f"- {h}" for h in hits)


def run_command(command: str, timeout: int = 30) -> str:
    """在允许根目录内执行一条命令。

    出于安全，默认关闭：只有 .env 里显式设置 WAIBao_ENABLE_EXEC=1 才可用；
    并且应只在「本机运行」时开启，公开部署（陌生人可访问）请务必保持关闭。
    """
    if os.environ.get("WAIBao_ENABLE_EXEC") != "1":
        return (
            "（执行命令功能默认关闭，出于安全考虑。"
            "如在本机使用，请在项目 .env 中加一行 WAIBao_ENABLE_EXEC=1 后重启；"
            "公开链接请不要开启，以免被陌生人利用。）"
        )
    command = command.strip()
    if not command:
        return "（请提供要执行的命令）"
    base = _allowed_root()
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(base),
        )
    except subprocess.TimeoutExpired:
        return f"（命令执行超时（超过 {timeout} 秒），已终止）"
    except Exception as exc:  # noqa: BLE001
        return f"（执行失败：{exc}）"
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return out[:4000] if out else "（命令执行完成，无输出）"
