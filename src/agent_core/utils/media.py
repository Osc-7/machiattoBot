"""
多模态媒体辅助函数。

用于将本地图片/视频文件转换为可注入 OpenAI 兼容 messages 的 content item。
远程工作区下，异步接口会经 blob_pull_to_path 把图片物化到 daemon 本地缓存后再挂载。
"""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from macchiato_remote.protocol import (
    REMOTE_BLOB_STREAM_MAX_BYTES,
    REMOTE_BLOB_TRANSFER_TIMEOUT_SECONDS,
    format_byte_size,
    parse_file_too_large,
)

if TYPE_CHECKING:
    from agent_core.config import Config

_VIDEO_SUFFIXES = {
    ".mp4",
    ".webm",
    ".mov",
    ".mkv",
    ".avi",
    ".m4v",
    ".mpeg",
    ".mpg",
}

_DISCONNECT_MARKERS = (
    "未连接",
    "disconnected",
    "ConnectionClosed",
    "MessageTooBig",
    "frame is too large",
    "message too big",
    "exceeded limit",
)


def remote_blob_too_large_message(
    *,
    actual_bytes: Optional[int] = None,
    limit_bytes: int,
    kind: str = "文件",
) -> str:
    limit_s = format_byte_size(limit_bytes)
    if actual_bytes is not None and int(actual_bytes) > 0:
        return (
            f"远程{kind}过大（{format_byte_size(int(actual_bytes))}，"
            f"上限 {limit_s}），无法经 WebSocket 完整传输。"
            "请压缩或截短后再试。"
        )
    return (
        f"远程{kind}过大，超过 {limit_s} 上限，无法经 WebSocket 完整传输。"
        "请压缩或截短后再试。"
    )


def remote_worker_disconnect_message(*, kind: str = "附件") -> str:
    return (
        f"远程 worker 未连接，未能读取{kind}。"
        "若正在传输较大文件，常见原因是超过 WebSocket 帧上限把连接打掉了"
        "（看起来像断联，实际是文件过大）。请压缩后再试，并升级 macchiato-remote。"
    )


def looks_like_remote_worker_disconnect(exc: BaseException) -> bool:
    blob = f"{exc.__class__.__name__}: {exc}"
    lowered = blob.lower()
    return any(m.lower() in lowered for m in _DISCONNECT_MARKERS)


def interpret_remote_blob_read(
    blob: Any,
    *,
    limit_bytes: int,
    kind: str = "文件",
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    """Normalize worker blob result.

    Returns ``(payload, error_message, error_code)`` where ``error_code`` is
    ``TOO_LARGE`` / ``READ_FAILED`` / ``None``.
    """
    parsed = parse_file_too_large(getattr(blob, "error", None))
    if parsed is not None:
        actual, limit = parsed
        return (
            None,
            remote_blob_too_large_message(
                actual_bytes=actual, limit_bytes=limit, kind=kind
            ),
            "TOO_LARGE",
        )
    err = getattr(blob, "error", None)
    if err:
        return None, str(err), "READ_FAILED"
    if bool(getattr(blob, "truncated", False)):
        return (
            None,
            remote_blob_too_large_message(
                actual_bytes=None,
                limit_bytes=limit_bytes,
                kind=kind,
            ),
            "TOO_LARGE",
        )
    content_b64 = getattr(blob, "content_base64", None) or ""
    if not content_b64:
        return None, f"远程{kind}为空", "READ_FAILED"
    return (
        {
            "content_base64": content_b64,
            "file_name": getattr(blob, "file_name", None) or "",
            "mime_type": getattr(blob, "mime_type", None) or "application/octet-stream",
            "bytes_read": getattr(blob, "bytes_read", 0) or 0,
            "truncated": False,
        },
        None,
        None,
    )


def _project_root() -> Path:
    # /work/src/agent/utils/media.py -> /work
    return Path(__file__).resolve().parents[3]


def _resolve_media_path(
    media_path: str,
    *,
    config: Optional["Config"] = None,
    exec_ctx: Optional[dict] = None,
) -> Path:
    """
    将媒体路径解析为绝对路径。

    解析策略：
    1) ``~`` / ``~/``：若传入 ``config``，与会话工作区对齐（见 ``session_paths``）
    2) 绝对路径：直接使用
    3) 相对路径：与 file_tools 一致，优先相对当前会话工作区（隔离开启时）或
       file_tools.base_dir；若不存在再尝试项目根与 ``user_file/``（兼容旧行为）
    """
    raw = (media_path or "").strip()
    if config is not None:
        from agent_core.agent.session_paths import expand_user_path_str_for_session

        raw = expand_user_path_str_for_session(raw, config, exec_ctx=exec_ctx or {})
    else:
        raw = str(Path(raw).expanduser())
    p = Path(raw)
    if p.is_absolute():
        return p.resolve()

    root = _project_root()

    if config is not None:
        from agent_core.agent.tool_path_resolution import resolve_path_string_for_tool

        session_path, _err = resolve_path_string_for_tool(raw, config, exec_ctx or {})
        if session_path is not None and session_path.exists():
            return session_path.resolve()

    direct = (root / p).resolve()
    if direct.exists():
        return direct

    return (root / "user_file" / p).resolve()


def _remote_workspace_active(exec_ctx: Optional[dict]) -> bool:
    sid = str((exec_ctx or {}).get("session_id") or "").strip()
    if not sid:
        return False
    try:
        from agent_core.remote.workspace_state import get_remote_workspace_state

        return get_remote_workspace_state(sid) is not None
    except Exception:
        return False


def _file_to_data_url(path: Path) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    将文件编码为 data URL。

    Returns:
        (data_url, mime, error)
    """
    if not path.exists() or not path.is_file():
        return None, None, f"媒体文件不存在: {path}"

    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        mime = "application/octet-stream"

    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}", mime, None


def _media_ref_from_path(path: Path, *, mime: Optional[str] = None) -> Dict[str, Any]:
    resolved_mime = (mime or "").strip() or (
        mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    )
    if (resolved_mime or "").startswith(
        "video/"
    ) or path.suffix.lower() in _VIDEO_SUFFIXES:
        media_type = "video"
    else:
        media_type = "image"
    return {
        "type": "media_ref",
        "media_type": media_type,
        "path": str(path),
        "name": path.name,
        "mime_type": resolved_mime,
    }


def _safe_session_cache_key(session_id: str) -> str:
    raw = (session_id or "unknown").strip() or "unknown"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", raw)[:48].strip("._") or "session"
    return f"{cleaned}-{digest}"


def _remote_media_cache_dir(session_id: str) -> Path:
    root = (
        Path(tempfile.gettempdir())
        / "macchiato_remote_media"
        / _safe_session_cache_key(session_id)
    )
    root.mkdir(parents=True, exist_ok=True)
    return root


def _remote_media_cache_name(rel: str, file_name: str) -> str:
    name = Path(file_name or "remote_media.bin").name
    stem = Path(name).stem or "media"
    suffix_name = Path(name).suffix or ".bin"
    digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:10]
    return f"{stem}-{digest}{suffix_name}"


def resolve_media_to_content_item(
    media_path: str,
    *,
    config: Optional["Config"] = None,
    exec_ctx: Optional[dict] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    将媒体路径转换为多模态 content item（media_ref）。

    传入 ``config`` / ``exec_ctx`` 时，``~`` 与会话工作区一致（与 attach_media 路径对齐）。

    远程工作区请使用 :func:`resolve_media_to_content_item_async`（会拉取到本地缓存）。

    Returns:
        (content_item, error)
    """
    if config is not None and _remote_workspace_active(exec_ctx):
        return (
            None,
            "远程工作区媒体需异步拉取；请用 attach_media / recognize_image（会自动从 worker 拉取）。",
        )
    path = _resolve_media_path(media_path, config=config, exec_ctx=exec_ctx)
    return _media_ref_from_path(path), None


async def resolve_media_to_content_item_async(
    media_path: str,
    *,
    config: Optional["Config"] = None,
    exec_ctx: Optional[dict] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """异步版：远程工作区下经 blob 流式拉取物化到 daemon 本地后再返回 media_ref。"""
    if config is not None and _remote_workspace_active(exec_ctx):
        return await _resolve_remote_media_to_content_item(
            media_path, config=config, exec_ctx=exec_ctx or {}
        )
    return resolve_media_to_content_item(media_path, config=config, exec_ctx=exec_ctx)


async def _resolve_remote_media_to_content_item(
    media_path: str,
    *,
    config: "Config",
    exec_ctx: dict,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    _ = config  # 保留签名与本地解析一致，供后续扩展 ACL
    raw = (media_path or "").strip()
    if not raw:
        return None, "媒体路径为空"

    suffix = Path(raw).suffix.lower()
    # 视频允许拉取；超限由 TOO_LARGE 分支报错

    sid = str((exec_ctx or {}).get("session_id") or "").strip()
    if not sid:
        return None, "缺少远程会话 session_id"

    try:
        from agent_core.remote.pathmap import normalize_remote_workspace_relative_path
        from agent_core.remote.worker_registry import get_remote_worker_registry
        from agent_core.remote.workspace_state import get_remote_workspace_state

        state = get_remote_workspace_state(sid)
        if state is None:
            return None, "远程会话未激活"
        rel, verr = normalize_remote_workspace_relative_path(raw)
        if verr or rel is None:
            return None, verr or "无效远程路径"

        blob = await get_remote_worker_registry().blob_pull_to_path(
            login=state.login,
            session_id=sid,
            path=rel,
            dest_path=_remote_media_cache_dir(sid)
            / _remote_media_cache_name(rel, Path(raw).name),
            max_bytes=REMOTE_BLOB_STREAM_MAX_BYTES,
        )
    except Exception as exc:
        if isinstance(exc, TimeoutError):
            secs = int(REMOTE_BLOB_TRANSFER_TIMEOUT_SECONDS)
            return None, f"远程拉取媒体超时（blob 传输 > {secs}s）"
        if looks_like_remote_worker_disconnect(exc):
            return None, remote_worker_disconnect_message(kind="媒体")
        exc_name = exc.__class__.__name__
        msg = str(exc).strip()
        if msg:
            return None, f"远程拉取媒体失败: {exc_name}: {msg}"
        return None, f"远程拉取媒体失败: {exc_name}"

    parsed = parse_file_too_large(blob.error)
    if parsed is not None:
        actual, limit = parsed
        return None, remote_blob_too_large_message(
            actual_bytes=actual, limit_bytes=limit, kind="媒体"
        )
    if blob.error:
        return None, blob.error
    if blob.truncated:
        return None, remote_blob_too_large_message(
            limit_bytes=REMOTE_BLOB_STREAM_MAX_BYTES, kind="媒体"
        )
    local_path = Path(blob.dest_path or "")
    if not local_path.is_file():
        return None, "远程媒体为空"

    mime = (blob.mime_type or "").strip() or (
        mimetypes.guess_type(blob.file_name or raw)[0] or "application/octet-stream"
    )
    if mime.startswith("video/") or suffix in _VIDEO_SUFFIXES:
        if not mime.startswith("video/"):
            mime = mimetypes.guess_type(blob.file_name or raw)[0] or "video/mp4"
    elif not mime.startswith("image/"):
        # 某些 worker 会返回 octet-stream；按扩展名再判一次
        guess = mimetypes.guess_type(blob.file_name or raw)[0] or ""
        if guess.startswith("image/"):
            mime = guess
        elif guess.startswith("video/") or suffix in _VIDEO_SUFFIXES:
            mime = guess or "video/mp4"
        else:
            return None, (
                f"远程路径不是图片/视频（mime={mime}），"
                "attach_media 仅支持 image/video"
            )

    return _media_ref_from_path(local_path, mime=mime), None
