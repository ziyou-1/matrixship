"""Runtime feature gates shared by MatrixShip platform boundaries."""

import os

try:
    from utils.structured_log import json_log
except ModuleNotFoundError:
    from backend.utils.structured_log import json_log


XHS_ENABLED_ENV = "MATRIX_XHS_ENABLED"
VIDEO_REPLACEMENT_ENABLED_ENV = "MATRIX_VIDEO_REPLACEMENT_ENABLED"
PENDING_PUBLISH_UI_ENABLED_ENV = "MATRIX_PENDING_PUBLISH_UI_ENABLED"
DIGITAL_HUMAN_TTS_UPLOAD_ENABLED_ENV = "MATRIX_DIGITAL_HUMAN_TTS_UPLOAD_ENABLED"
_TRUTHY = {"1", "true", "yes", "on"}
_XHS_ALIASES = {"xhs", "xiaohongshu", "rednote", "小红书"}


def env_flag_enabled(name, env=None, default=False):
    values = os.environ if env is None else env
    raw = values.get(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in _TRUTHY


def xhs_enabled(env=None):
    return env_flag_enabled(XHS_ENABLED_ENV, env=env)


def video_replacement_enabled(env=None):
    return env_flag_enabled(VIDEO_REPLACEMENT_ENABLED_ENV, env=env)


def pending_publish_ui_enabled(env=None):
    return env_flag_enabled(PENDING_PUBLISH_UI_ENABLED_ENV, env=env)


def digital_human_tts_upload_enabled(env=None):
    return env_flag_enabled(DIGITAL_HUMAN_TTS_UPLOAD_ENABLED_ENV, env=env)


def filter_xhs_capabilities(capabilities, env=None):
    values = list(capabilities or [])
    if xhs_enabled(env):
        return values
    return [
        value
        for value in values
        if not str(value or "").strip().lower().startswith("xhs.")
    ]


def is_xhs_platform(value):
    return str(value or "").strip().lower() in _XHS_ALIASES


def payload_uses_xhs(payload):
    if not isinstance(payload, dict):
        return False
    candidates = [
        payload.get("platform"),
        payload.get("pf"),
        payload.get("sourcePlatform"),
        payload.get("publishPlatform"),
        payload.get("accountId"),
        payload.get("account"),
        payload.get("type"),
    ]
    nested_payload = payload.get("payload")
    if isinstance(nested_payload, dict) and payload_uses_xhs(nested_payload):
        return True
    material = payload.get("material")
    if isinstance(material, dict):
        candidates.extend(
            [material.get("platform"), material.get("accountId"), material.get("account")]
        )
    return any(is_xhs_platform(value) or "xhs" in str(value or "").lower() for value in candidates)


def platform_disabled_result(platform, route="", task_type="", stage="preflight"):
    result = {
        "ok": False,
        "error": "platform_disabled",
        "platform": "xhs" if is_xhs_platform(platform) else str(platform or ""),
        "stage": str(stage or "preflight"),
        "message": "platform_disabled",
    }
    if route:
        result["route"] = str(route)
    if task_type:
        result["taskType"] = str(task_type)
    return result


def require_platform_enabled(platform, route="", task_type="", stage="preflight"):
    if is_xhs_platform(platform) and not xhs_enabled():
        return platform_disabled_result(platform, route, task_type, stage)
    return None


def log_platform_disabled(log, platform, route="", task_type="", stage="preflight"):
    return json_log(
        log,
        "platform_disabled",
        level="warning",
        platform="xhs" if is_xhs_platform(platform) else str(platform or ""),
        route=str(route or ""),
        taskType=str(task_type or ""),
        stage=str(stage or "preflight"),
    )
