import json
import math
import os
import re
import shutil
import subprocess
import time


_ERROR_CONTENT_TYPES = {
    "application/json",
    "application/problem+json",
    "application/xml",
    "text/html",
    "text/plain",
    "text/xml",
}


def _ffmpeg_exe():
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _parse_duration(text):
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text or "")
    if not match:
        return 0.0
    return round(
        int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3)),
        3,
    )


def _parse_dimensions(text):
    for line in (text or "").splitlines():
        if "Video:" not in line:
            continue
        for match in re.finditer(r"(?<!\d)(\d{2,5})x(\d{2,5})(?!\d)", line):
            width, height = int(match.group(1)), int(match.group(2))
            if 1 <= width <= 16384 and 1 <= height <= 16384:
                return width, height
    return 0, 0


def probe_media(path, ffmpeg_exe=None):
    result = {
        "duration": 0.0,
        "width": 0,
        "height": 0,
        "hasVideo": False,
        "hasAudio": False,
        "path": path or "",
    }
    if not (path and os.path.isfile(path)):
        result["error"] = "media_missing_file"
        return result
    try:
        completed = subprocess.run(
            [ffmpeg_exe or _ffmpeg_exe(), "-hide_banner", "-i", path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        raw = (completed.stderr or "") + "\n" + (completed.stdout or "")
        width, height = _parse_dimensions(raw)
        result.update({
            "duration": _parse_duration(raw),
            "width": width,
            "height": height,
            "hasVideo": any("Video:" in line for line in raw.splitlines()),
            "hasAudio": any("Audio:" in line for line in raw.splitlines()),
        })
        if not result["hasVideo"]:
            result["error"] = "media_missing_video_stream"
    except Exception as exc:
        result["error"] = "media_probe_failed"
        result["detail"] = str(exc)[:200]
    return result


def looks_like_error_document(path):
    if not (path and os.path.isfile(path)):
        return False
    try:
        with open(path, "rb") as handle:
            head = handle.read(4096).lstrip().lower()
    except Exception:
        return False
    markers = (
        b"<html",
        b"<!doctype html",
        b"<head>",
        b"403 forbidden",
        b"404 not found",
        b"access denied",
    )
    return any(marker in head for marker in markers)


def _decode_timeout_seconds(duration):
    try:
        configured = float(str(os.getenv("MEDIA_DECODE_TIMEOUT_SEC", "") or "").strip())
    except (TypeError, ValueError):
        configured = 0.0
    if math.isfinite(configured) and configured > 0:
        return configured
    try:
        duration_value = float(duration)
    except (TypeError, ValueError):
        return 60.0
    if not math.isfinite(duration_value):
        return 60.0
    return max(60.0, min(600.0, duration_value * 0.75))


def validate_video_file(path, content_type="", ffmpeg_exe=None):
    base = {
        "ok": False,
        "code": "media_invalid",
        "path": path or "",
        "size": 0,
        "duration": 0.0,
        "width": 0,
        "height": 0,
        "hasVideo": False,
        "hasAudio": False,
    }
    if not (path and os.path.isfile(path)):
        base["code"] = "media_missing_file"
        return base
    base["size"] = os.path.getsize(path)
    if base["size"] <= 0:
        base["code"] = "media_empty_file"
        return base
    normalized_type = str(content_type or "").split(";", 1)[0].strip().lower()
    if normalized_type in _ERROR_CONTENT_TYPES or normalized_type.startswith("text/"):
        base["code"] = "download_unexpected_content_type"
        base["contentType"] = normalized_type
        return base
    if looks_like_error_document(path):
        base["code"] = "download_html_body"
        return base
    meta = probe_media(path, ffmpeg_exe=ffmpeg_exe)
    base.update({key: meta.get(key, base[key]) for key in (
        "duration", "width", "height", "hasVideo", "hasAudio"
    )})
    if not meta.get("hasVideo"):
        base["code"] = meta.get("error") or "media_missing_video_stream"
        return base
    if float(meta.get("duration") or 0) <= 0:
        base["code"] = "media_invalid_duration"
        return base
    if int(meta.get("width") or 0) <= 0 or int(meta.get("height") or 0) <= 0:
        base["code"] = "media_invalid_dimensions"
        return base
    try:
        decoded = subprocess.run(
            [
                ffmpeg_exe or _ffmpeg_exe(),
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-xerror",
                "-i",
                path,
                "-map",
                "0:v:0",
                "-f",
                "null",
                "-",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_decode_timeout_seconds(meta.get("duration")),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        base["code"] = "media_decode_timeout"
        return base
    except Exception:
        base["code"] = "media_decode_failed"
        return base
    if decoded.returncode != 0:
        base["code"] = "media_decode_failed"
        return base
    base["ok"] = True
    base["code"] = "ok"
    if normalized_type:
        base["contentType"] = normalized_type
    return base


def validate_image_file(path, content_type=""):
    base = {
        "ok": False,
        "code": "media_invalid",
        "path": path or "",
        "size": 0,
        "width": 0,
        "height": 0,
        "format": "",
    }
    if not (path and os.path.isfile(path)):
        base["code"] = "media_missing_file"
        return base
    base["size"] = os.path.getsize(path)
    if base["size"] <= 0:
        base["code"] = "media_empty_file"
        return base
    normalized_type = str(content_type or "").split(";", 1)[0].strip().lower()
    if normalized_type in _ERROR_CONTENT_TYPES or normalized_type.startswith("text/"):
        base["code"] = "download_unexpected_content_type"
        base["contentType"] = normalized_type
        return base
    if looks_like_error_document(path):
        base["code"] = "download_html_body"
        return base
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            width, height = image.size
            image_format = str(image.format or "")
    except Exception:
        base["code"] = "media_image_decode_failed"
        return base
    if int(width or 0) <= 0 or int(height or 0) <= 0:
        base["code"] = "media_invalid_dimensions"
        return base
    base.update({
        "ok": True,
        "code": "ok",
        "width": int(width),
        "height": int(height),
        "format": image_format,
    })
    if normalized_type:
        base["contentType"] = normalized_type
    return base


def _safe_component(value, fallback):
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    return cleaned[:120] or fallback


def quarantine_file(path, quarantine_root, material_id, reason):
    if not (path and os.path.isfile(path)):
        return ""
    stamp = time.strftime("%Y%m%d_%H%M%S") + ("_%03d" % int((time.time() % 1) * 1000))
    target_dir = os.path.join(
        quarantine_root,
        _safe_component(material_id, "unknown-material"),
        stamp,
    )
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, os.path.basename(path))
    try:
        os.replace(path, target)
    except OSError:
        shutil.copy2(path, target)
        os.remove(path)
    metadata = {
        "materialId": str(material_id or ""),
        "reason": str(reason or "media_invalid"),
        "originalPath": os.path.abspath(path),
        "quarantinedAt": time.time(),
    }
    with open(os.path.join(target_dir, "metadata.json"), "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)
    return target


def cleanup_quarantine(root, retention_days):
    if not os.path.isdir(root):
        return 0
    cutoff = time.time() - max(0, int(retention_days or 0)) * 86400
    removed = 0
    for material_name in list(os.listdir(root)):
        material_dir = os.path.join(root, material_name)
        if not os.path.isdir(material_dir):
            continue
        for stamp_name in list(os.listdir(material_dir)):
            stamp_dir = os.path.join(material_dir, stamp_name)
            if not os.path.isdir(stamp_dir):
                continue
            try:
                expired = os.path.getmtime(stamp_dir) < cutoff
            except OSError:
                expired = False
            if expired:
                shutil.rmtree(stamp_dir, ignore_errors=True)
                removed += 1
        try:
            if not os.listdir(material_dir):
                os.rmdir(material_dir)
        except OSError:
            pass
    return removed
