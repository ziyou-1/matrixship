import base64
import ipaddress
import json
import os
import re
import subprocess
import time
from urllib.parse import quote, urlsplit

import requests

from utils.media_validation import probe_media
from utils.structured_log import json_log


class _NoopLogger:
    def error(self, _value):
        pass

    def info(self, _value):
        pass


def validate_service_url(value):
    url = str(value or "").strip()
    parsed = urlsplit(url)
    scheme = str(parsed.scheme or "").lower()
    host = str(parsed.hostname or "").lower().rstrip(".")
    if scheme not in {"http", "https"} or not host:
        raise ValueError("service URL must be an absolute http/https URL")
    if scheme == "https":
        return url
    loopback = host == "localhost"
    if not loopback:
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
    if not loopback:
        raise ValueError("remote service URL must use https; http is allowed only for loopback hosts")
    return url


def build_chunk_ranges(duration, chunk_sec=60, max_sec=None):
    duration = max(0.0, float(duration or 0))
    chunk_sec = max(1.0, float(chunk_sec or 60))
    configured_max = float(max_sec or 0)
    max_sec = max(chunk_sec, configured_max) if configured_max > 0 else duration
    limit = min(duration, max_sec)
    ranges = []
    start = 0.0
    while start < limit:
        end = min(limit, start + chunk_sec)
        ranges.append({"start": round(start, 3), "end": round(end, 3)})
        start = end
    return {"ranges": ranges, "truncated": duration > max_sec, "duration": duration, "limit": limit}


def export_audio_chunks(video_path, out_dir, chunk_sec=60, max_sec=None,
                        ffmpeg_exe=None, probe_fn=None, run_fn=None,
                        only_ranges=None, logger=None):
    logger = logger or _NoopLogger()
    if not (video_path and os.path.isfile(video_path)):
        return {"status": "failed", "code": "media_missing_file", "chunks": [],
                "failedRanges": [], "errors": [], "truncated": False}
    probe_fn = probe_fn or probe_media
    meta = probe_fn(video_path) or {}
    duration = float(meta.get("duration") or 0)
    if duration <= 0:
        return {"status": "failed", "code": "media_invalid_duration", "chunks": [],
                "failedRanges": [], "errors": [], "truncated": False}
    ranges = build_chunk_ranges(duration, chunk_sec=chunk_sec, max_sec=max_sec)
    if meta.get("hasAudio") is False:
        return {"status": "no_audio", "code": "media_missing_audio_stream", "chunks": [],
                "failedRanges": [], "errors": [],
                "duration": duration,
                "limit": ranges["limit"],
                "truncated": bool(ranges["truncated"])}
    os.makedirs(out_dir, exist_ok=True)
    if ffmpeg_exe is None:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    run_fn = run_fn or subprocess.run
    chunks = []
    failures = []
    selected_ranges = [
        item for item in ranges["ranges"] if _range_selected(item, only_ranges)
    ]
    for item in selected_ranges:
        start = float(item["start"])
        end = float(item["end"])
        target = os.path.join(out_dir, "chunk_%06d.mp3" % int(round(start * 1000)))
        cmd = [
            ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error",
            "-ss", "%.3f" % start, "-i", video_path,
            "-t", "%.3f" % max(0.001, end - start),
            "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", target,
        ]
        try:
            if os.path.isfile(target):
                os.remove(target)
            run_fn(
                cmd,
                check=True,
                capture_output=True,
                timeout=max(30, int(end - start) * 3),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if not (os.path.isfile(target) and os.path.getsize(target) > 0):
                raise RuntimeError("audio_export_empty_output")
            chunks.append({"start": start, "end": end, "path": target})
        except Exception as exc:
            code = "audio_export_timeout" if isinstance(exc, subprocess.TimeoutExpired) else "audio_export_failed"
            raw = json_log(
                logger,
                "video_audio_chunk_export_failed",
                exc=exc,
                code=code,
                chunk_start=start,
                chunk_end=end,
                ffmpeg_exe=ffmpeg_exe,
                return_code=getattr(exc, "returncode", None),
                stderr=getattr(exc, "stderr", None),
            )
            error_id = (json.loads(raw) or {}).get("errorId")
            failures.append({"start": start, "end": end, "code": code, "errorId": error_id})
    if chunks and failures:
        status = "partial"
        code = "audio_export_partial"
    elif chunks:
        status = "ok"
        code = "ok"
    else:
        status = "failed"
        code = failures[0]["code"] if failures else "audio_export_failed"
    return {
        "status": status,
        "code": code,
        "chunks": chunks,
        "failedRanges": failures,
        "errors": list(failures),
        "duration": duration,
        "limit": ranges["limit"],
        "truncated": bool(ranges["truncated"]),
    }


def validate_transcription_response(value):
    if not isinstance(value, dict) or set(value.keys()) != {"language", "segments"}:
        return {"ok": False, "code": "transcription_schema_object"}
    language = value.get("language")
    segments = value.get("segments")
    if not isinstance(language, str) or not (1 <= len(language.strip()) <= 32):
        return {"ok": False, "code": "transcription_schema_language"}
    if not isinstance(segments, list):
        return {"ok": False, "code": "transcription_schema_segments"}
    normalized = []
    for segment in segments:
        if not isinstance(segment, dict) or set(segment.keys()) != {"startSec", "endSec", "text"}:
            return {"ok": False, "code": "transcription_schema_segment"}
        start = segment.get("startSec")
        end = segment.get("endSec")
        text = segment.get("text")
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            return {"ok": False, "code": "transcription_schema_time"}
        start, end = float(start), float(end)
        if start < 0 or end < start or start > 60 or end > 60:
            return {"ok": False, "code": "transcription_schema_time"}
        if not isinstance(text, str) or not (1 <= len(text.strip()) <= 4000):
            return {"ok": False, "code": "transcription_schema_text"}
        normalized.append({"startSec": start, "endSec": end, "text": text.strip()})
    return {"ok": True, "code": "ok", "value": {"language": language.strip(), "segments": normalized}}


def _format_timestamp(seconds):
    total_ms = max(0, int(round(float(seconds or 0) * 1000)))
    minutes, rem_ms = divmod(total_ms, 60000)
    secs, millis = divmod(rem_ms, 1000)
    return "%02d:%02d.%03d" % (minutes, secs, millis)


def _compact_overlap_text(value):
    return re.sub(r"\s+", "", str(value or "").strip())


def _drop_compact_prefix(value, compact_chars):
    if compact_chars <= 0:
        return str(value or "").strip()
    seen = 0
    text = str(value or "")
    for index, char in enumerate(text):
        if char.isspace():
            continue
        seen += 1
        if seen >= compact_chars:
            return text[index + 1:].strip()
    return ""


def remove_adjacent_text_overlap(previous, current, min_chars=8):
    current_text = str(current or "").strip()
    if not current_text:
        return ""
    previous_compact = _compact_overlap_text(previous)
    current_compact = _compact_overlap_text(current_text)
    if not previous_compact or not current_compact:
        return current_text
    limit = min(len(previous_compact), len(current_compact))
    threshold = max(1, int(min_chars or 1))
    for size in range(limit, threshold - 1, -1):
        if previous_compact[-size:] == current_compact[:size]:
            return _drop_compact_prefix(current_text, size)
    return current_text


def merge_transcription_segments(chunks):
    segments = []
    language = ""
    coarse = False
    previous_text = ""
    for chunk in chunks or []:
        offset = float(chunk.get("start") or 0)
        language = language or str(chunk.get("language") or "")
        coarse = coarse or bool(chunk.get("coarseTimestamps"))
        for segment in chunk.get("segments") or []:
            start = round(offset + float(segment.get("startSec") or 0), 3)
            end = round(offset + float(segment.get("endSec") or 0), 3)
            text = str(segment.get("text") or "").strip()
            if text:
                text = remove_adjacent_text_overlap(previous_text, text)
            if text:
                segments.append({"startSec": start, "endSec": end, "text": text})
                previous_text = text
    segments.sort(key=lambda row: (row["startSec"], row["endSec"]))
    lines = [
        "[%s-%s] %s" % (_format_timestamp(row["startSec"]), _format_timestamp(row["endSec"]), row["text"])
        for row in segments
    ]
    return {"language": language, "segments": segments, "text": "\n".join(lines),
            "coarseTimestamps": coarse}


def _candidate_text(payload):
    texts = []
    if isinstance(payload, dict):
        for candidate in payload.get("candidates") or []:
            content = candidate.get("content") if isinstance(candidate, dict) else {}
            for part in (content or {}).get("parts") or []:
                text = part.get("text") if isinstance(part, dict) else ""
                if text:
                    texts.append(str(text))
    return "\n".join(texts).strip()


def _parse_candidate(text, chunk_duration):
    raw = str(text or "").strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.I | re.S)
    if fenced:
        raw = fenced.group(1).strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        if raw.lstrip("\ufeff \t\r\n").startswith(("{", "[")):
            raise RuntimeError("transcription_invalid_json")
        value = None
    else:
        checked = validate_transcription_response(value)
        if not checked.get("ok"):
            raise RuntimeError(checked.get("code") or "transcription_invalid_response")
        parsed = checked["value"]
        if any(_looks_like_transcription_refusal(segment.get("text"))
               for segment in parsed.get("segments") or []):
            raise RuntimeError("transcription_refused")
        return dict(parsed, coarseTimestamps=False)
    fallback_text = str(text or "").strip()
    if fallback_text and _looks_like_transcription_refusal(fallback_text):
        raise RuntimeError("transcription_refused")
    if fallback_text:
        if not _looks_like_transcription_body(fallback_text):
            raise RuntimeError("transcription_invalid_response")
        return {
            "language": "unknown",
            "segments": [{"startSec": 0.0, "endSec": float(chunk_duration), "text": fallback_text}],
            "coarseTimestamps": True,
        }
    raise RuntimeError("transcription_empty_response")


def _looks_like_transcription_refusal(text):
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if not value:
        return False
    patterns = (
        r"\b(?:i\s+(?:cannot|can't|am unable to)|unable to|cannot|can't)\s+"
        r"(?:help\s+(?:you\s+)?(?:with\s+)?)?(?:access|process|listen\s+to|transcrib)",
        r"\b(?:i(?:\s+am|'m)?\s+)?unable to\s+"
        r"(?:fulfill|comply|assist|help|complete|perform)\b",
        r"\b(?:there (?:was|is) an error|error (?:processing|transcribing)|"
        r"audio (?:could not|couldn't) be (?:processed|transcribed))\b",
        r"(?:\u65e0\u6cd5|\u4e0d\u80fd|\u6ca1\u6cd5|\u4e0d\u53ef\u4ee5).{0,12}(?:\u8bbf\u95ee|\u8bfb\u53d6|\u5904\u7406|\u8bc6\u522b|\u542c\u53d6|\u8f6c\u5199|\u8f6c\u5f55).{0,12}(?:\u97f3\u9891|\u8bed\u97f3|\u6587\u4ef6)?",
        r"(?:\u4f5c\u4e3a(?:\u4e00\u4e2a)?\s*AI|\u6211\u662f(?:\u4e00\u4e2a)?\s*AI).{0,32}(?:\u65e0\u6cd5|\u4e0d\u80fd|\u4e0d\u5177\u5907|\u6ca1\u6709\u80fd\u529b)",
        r"(?:\u97f3\u9891|\u8bed\u97f3|\u6587\u4ef6).{0,12}(?:\u5904\u7406|\u8f6c\u5199|\u8f6c\u5f55|\u8bc6\u522b)(?:\u5931\u8d25|\u51fa\u9519|\u9519\u8bef)",
    )
    return any(re.search(pattern, value, re.I | re.S) for pattern in patterns)


def _looks_like_transcription_body(text):
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if not value:
        return False
    if re.search(r"[\u4e00-\u9fff]", value):
        return True
    if re.search(r"\[\d{1,2}:\d{2}(?:\.\d+)?-\d{1,2}:\d{2}(?:\.\d+)?\]", value):
        return True
    if re.search(r"\b\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?\b", value):
        return True
    if re.search(r"\b(?:transcription|transcribe|json transcription|speech|subtitle|subtitles)\b", value, re.I):
        return False
    letters = len(re.findall(r"[A-Za-z]", value))
    digits = len(re.findall(r"\d", value))
    nonspace = len(re.sub(r"\s+", "", value))
    if nonspace == 0:
        return False
    if letters and letters >= nonspace * 0.6 and not digits:
        return False
    return letters == 0 or letters < nonspace * 0.5


def _range_selected(chunk, only_ranges):
    if not only_ranges:
        return True
    start, end = float(chunk.get("start") or 0), float(chunk.get("end") or 0)
    return any(
        abs(start - float(item.get("start") or 0)) < 0.001
        and abs(end - float(item.get("end") or 0)) < 0.001
        for item in only_ranges if isinstance(item, dict)
    )


def _billing_context_headers(context):
    if not isinstance(context, dict):
        return {}
    mapping = {
        "scenario": "X-Matrix-Billing-Scenario",
        "stage": "X-Matrix-Billing-Stage",
        "detail": "X-Matrix-Billing-Detail",
    }
    headers = {}
    for key, header in mapping.items():
        value = str(context.get(key) or "").strip()
        if value:
            headers[header] = value[:160]
    return headers


def transcribe_audio_chunks(chunks, base_url, api_key, model, timeout, retries,
                            proxies=None, only_ranges=None, progress=None,
                            request_fn=None, sleep_fn=None, logger=None,
                            billing_context=None):
    request_fn = request_fn or requests.post
    sleep_fn = sleep_fn or time.sleep
    logger = logger or _NoopLogger()
    base_url = validate_service_url(base_url)
    selected = [chunk for chunk in (chunks or []) if _range_selected(chunk, only_ranges)]
    successes = []
    failures = []
    errors = []
    endpoint = "%s/v1beta/models/%s:generateContent" % (
        str(base_url or "").rstrip("/"), quote(str(model or ""), safe="")
    )
    for index, chunk in enumerate(selected):
        start, end = float(chunk.get("start") or 0), float(chunk.get("end") or 0)
        last_exc = None
        for attempt in range(max(0, int(retries or 0)) + 1):
            try:
                with open(chunk.get("path") or "", "rb") as handle:
                    encoded = base64.b64encode(handle.read()).decode("ascii")
                prompt = (
                    "请准确转写这段中文短视频口播。只返回 JSON，不要 Markdown。"
                    "格式为 {\"language\":\"zh-CN\",\"segments\":["
                    "{\"startSec\":0.0,\"endSec\":1.0,\"text\":\"文字\"}]}。"
                    "时间必须是本音频分片内的相对秒数，范围 0 到 %.3f。"
                ) % max(0.0, end - start)
                body = {
                    "contents": [{"role": "user", "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": "audio/mpeg", "data": encoded}},
                    ]}],
                    "generationConfig": {"temperature": 0.1},
                }
                headers = {
                    "Authorization": "Bearer " + str(api_key or ""),
                    "Content-Type": "application/json",
                }
                headers.update(_billing_context_headers(billing_context))
                response = request_fn(
                    endpoint,
                    headers=headers,
                    json=body,
                    timeout=timeout,
                    verify=True,
                    proxies=proxies,
                )
                encoded = ""
                body = None
                if int(getattr(response, "status_code", 0) or 0) != 200:
                    raise RuntimeError("transcription_http_%s" % getattr(response, "status_code", 0))
                parsed = _parse_candidate(_candidate_text(response.json()), max(0.0, end - start))
                successes.append(dict(chunk, **parsed))
                if callable(progress):
                    progress(index, len(selected), start, end, "ok")
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                if attempt < max(0, int(retries or 0)):
                    sleep_fn(min(5, 2 ** attempt))
        if last_exc is not None:
            if isinstance(last_exc, (TimeoutError, requests.exceptions.Timeout)):
                code = "remote_timeout"
            elif str(last_exc) in {"transcription_refused", "transcription_invalid_json"}:
                code = str(last_exc)
            elif str(last_exc).startswith("transcription_schema_"):
                code = "transcription_invalid_response"
            else:
                code = "remote_error"
            raw = json_log(logger, "video_transcription_chunk_failed", exc=last_exc,
                           code=code, chunk_start=start, chunk_end=end, model=model)
            error_id = (json.loads(raw) or {}).get("errorId")
            failure = {"start": start, "end": end, "code": code, "errorId": error_id}
            failures.append(failure)
            errors.append(failure)
            if callable(progress):
                progress(index, len(selected), start, end, "failed")
    merged = merge_transcription_segments(successes)
    if successes and failures:
        status = "partial"
    elif successes:
        status = "ok"
    elif failures:
        status = "failed"
    else:
        status = "empty"
    return dict(merged, status=status, chunks=successes, failedRanges=failures, errors=errors)
