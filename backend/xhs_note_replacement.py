import os
import uuid
from typing import Mapping, Optional


FEATURE_ENV = "XHS_NOTE_REPLACEMENT_ENABLED"
PUBLISH_FEATURE_ENV = "XHS_NOTE_PUBLISH_ENABLED"
XHS_TITLE_LIMIT = 20


def feature_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    source = os.environ if env is None else env
    raw = str(source.get(FEATURE_ENV, "1") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def new_job_id() -> str:
    return "xnr_" + uuid.uuid4().hex[:24]


def job_root(data_dir: str) -> str:
    return os.path.join(data_dir, "xhs_note_replacements")

import re
import time
from urllib.parse import urlparse


def _note_id_from_url(url: str) -> str:
    path = urlparse(str(url or "")).path.strip("/")
    parts = [p for p in path.split("/") if p]
    if "explore" in parts:
        idx = parts.index("explore")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return parts[-1] if parts else ""


def infer_slot_role(index: int, total: int, name: str = "") -> str:
    if index <= 1:
        return "cover"
    if total <= 2:
        return "cta" if index == total else "product"
    if index == total:
        return "cta"
    if index == total - 1 and total >= 5:
        return "result"
    if index == 2:
        return "product"
    if re.search(r"scene|store|shop|门店|场景", str(name or ""), re.I):
        return "scene"
    return "detail"


def build_template(material: dict, source_note: Optional[dict] = None) -> dict:
    material = material or {}
    source_note = source_note or {}
    files = [str(x or "") for x in (material.get("files") or []) if str(x or "").strip()]
    source_url = material.get("sourceUrl") or source_note.get("url") or source_note.get("noteUrl") or ""
    total = len(files)
    slots = []
    for idx, name in enumerate(files, start=1):
        role = infer_slot_role(idx, total, name)
        slots.append({
            "index": idx,
            "role": role,
            "sourceFile": name,
            "analysis": "%s槽位，来自原图第%d张" % (role, idx),
            "ratio": material.get("ratio") or "3:4",
        })
    return {
        "id": "tpl_" + uuid.uuid4().hex[:24],
        "sourcePlatform": material.get("platform") or "xhs",
        "sourceNoteId": source_note.get("noteId") or material.get("noteId") or _note_id_from_url(source_url),
        "sourceMaterialId": material.get("id") or "",
        "sourceDownloadPath": material.get("sourceDownloadPath") or source_note.get("sourceDownloadPath") or source_note.get("savePath") or "",
        "sourceUrl": source_url,
        "imageSlots": slots,
        "copyStructure": {
            "titlePattern": "原始标题结构",
            "bodyPattern": ["开头钩子", "卖点", "场景", "行动引导"],
            "tagPattern": ["行业词", "地域词", "需求词"],
        },
        "originalCopy": {
            "title": material.get("title") or source_note.get("title") or "",
            "body": material.get("body") or source_note.get("body") or "",
            "tags": material.get("tags") or source_note.get("tags") or [],
        },
        "createdAt": time.time(),
    }


def _asset_for_role(role: str, assets: list[dict]) -> Optional[dict]:
    for asset in assets or []:
        if str(asset.get("slotRole") or asset.get("role") or "") == role:
            return asset
    return None


def _asset_for_slot(slot: dict, assets: list[dict]) -> Optional[dict]:
    slot_index = str((slot or {}).get("index") or "")
    for asset in assets or []:
        if slot_index and str(asset.get("slotIndex") or "") == slot_index:
            return asset
    return _asset_for_role((slot or {}).get("role") or "detail", assets)


def _xhs_title(text: str) -> str:
    title = re.sub(r"\s+", "", str(text or "").strip())
    return (title or "同款图文笔记")[:XHS_TITLE_LIMIT]


def copy_candidates(template: dict, business_input: dict) -> list[dict]:
    business_input = business_input or {}
    name = business_input.get("name") or "\u4f60\u7684\u4e1a\u52a1"
    region = business_input.get("region") or "\u672c\u5730"
    selling = [str(x) for x in (business_input.get("sellingPoints") or []) if str(x).strip()]
    first = selling[0] if selling else "\u6838\u5fc3\u5356\u70b9"
    audience = business_input.get("audience") or "\u76ee\u6807\u5ba2\u6237"
    selling_text = "\u3001".join(selling) or first
    selling_focus = selling_text[:80]
    return [
        {
            "title": _xhs_title("%s\uff5c%s\u600e\u4e48\u9009\u66f4\u7a33" % (region, name)),
            "body": "最近很多%s会问%s怎么选。我的建议是先把%s这几件事看清楚，再结合每天通勤、家庭乘坐和预算去判断。不要只看一个参数，也不要被单一优惠带着走；在%s看车时，可以把这些点逐项问清楚，现场试驾后再决定更稳，也更踏实。" % (audience, name, selling_focus, region),
            "tags": ["#%s" % region, "#%s" % name, "#\u540c\u57ce\u79cd\u8349"],
        },
        {
            "title": _xhs_title("%s\u503c\u4e0d\u503c\u5f97\u770b\uff1f\u5148\u770b%s" % (name, first)),
            "body": "看%s不用只盯配置表，%s这些点更容易影响后面的使用感受。适合%s先把需求列清楚：平时几个人坐、主要跑市区还是高速、能不能接受后期保养成本。这样再去试驾或现场看实车，沟通会更有方向，也更容易避开不适合自己的选择。" % (name, selling_focus, audience),
            "tags": ["#\u5c0f\u7ea2\u4e66\u56fe\u6587", "#%s" % first, "#%s" % region],
        },
        {
            "title": _xhs_title("%s\u770b%s\uff0c\u8fd9\u51e0\u70b9\u5148\u95ee\u6e05\u695a" % (region, name)),
            "body": "如果你在%s准备看%s，可以先把%s问清楚。到店前确定好预算、用途和能接受的取舍，现场沟通会高效很多。尤其是第一次了解的人，建议把关心的问题提前写下来，逐项确认后再做决定；有不确定的地方，也可以先留给顾问帮你对比后再推进。" % (region, name, selling_focus),
            "tags": ["#\u907f\u5751", "#%s" % name, "#%s" % region],
        },
    ]


def build_replacement_preview(template: dict, business_input: dict, provided_assets: list[dict]) -> dict:
    mappings = []
    ai_count = 0
    for slot in template.get("imageSlots") or []:
        role = slot.get("role") or "detail"
        asset = _asset_for_slot(slot, provided_assets)
        if asset:
            mappings.append({
                "slotIndex": slot.get("index"),
                "slotRole": role,
                "source": "asset",
                "assetId": asset.get("assetId") or asset.get("id") or "",
                "filePath": asset.get("filePath") or asset.get("path") or "",
                "confirmationStatus": "confirmed",
            })
        else:
            ai_count += 1
            mappings.append({
                "slotIndex": slot.get("index"),
                "slotRole": role,
                "source": "ai_placeholder",
                "ratio": slot.get("ratio") or "3:4",
                "filePath": "",
                "confirmationStatus": "pending",
            })
    return {
        "templateId": template.get("id"),
        "slotMappings": mappings,
        "copyCandidates": copy_candidates(template, business_input),
        "selectedCopyIndex": 0,
        "aiSlotCount": ai_count,
    }


def replacement_material_error(job: dict) -> str:
    job = job or {}
    slots = job.get("template", {}).get("imageSlots") or []
    if not slots:
        return "xhs_note_no_template"
    for mapping in job.get("slotMappings") or []:
        if not str(mapping.get("filePath") or "").strip():
            return "xhs_note_replacement_missing_images"
    return ""

_JOB_ID_RE = re.compile(r"^xnr_[0-9a-f]{24}$")


def _validate_job_id(job_id: str) -> str:
    job_id = str(job_id or "").strip()
    if not _JOB_ID_RE.match(job_id):
        raise ValueError("invalid_job_id")
    return job_id


def save_job(data_dir: str, job: dict) -> str:
    job = dict(job or {})
    job_id = _validate_job_id(job.get("id"))
    root = os.path.join(job_root(data_dir), job_id)
    os.makedirs(root, exist_ok=True)
    final_path = os.path.join(root, "replacement_job.json")
    tmp_path = final_path + ".tmp"
    import json
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, final_path)
    return final_path


def load_job(data_dir: str, job_id: str) -> Optional[dict]:
    job_id = _validate_job_id(job_id)
    path = os.path.join(job_root(data_dir), job_id, "replacement_job.json")
    if not os.path.isfile(path):
        return None
    import json
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else None


def build_draft_material_payload(job: dict, saved_files: list[str]) -> dict:
    job = job or {}
    selected_idx = int(job.get("selectedCopyIndex") or 0)
    candidates = job.get("copyCandidates") or []
    copy = candidates[selected_idx] if 0 <= selected_idx < len(candidates) else {}
    pending = []
    confirmed = []
    for mapping in job.get("slotMappings") or []:
        slot_index = mapping.get("slotIndex")
        if mapping.get("source") == "ai_placeholder":
            if mapping.get("confirmationStatus") == "confirmed":
                confirmed.append(slot_index)
            else:
                pending.append(slot_index)
    return {
        "type": "image_note",
        "platform": "xhs",
        "title": copy.get("title") or "",
        "body": copy.get("body") or "",
        "tags": copy.get("tags") or [],
        "sourceTitle": (job.get("template") or {}).get("originalCopy", {}).get("title") or "",
        "sourceBody": (job.get("template") or {}).get("originalCopy", {}).get("body") or "",
        "sourceTags": (job.get("template") or {}).get("originalCopy", {}).get("tags") or [],
        "files": list(saved_files or []),
        "status": "draft",
        "published": 0,
        "aiImageReview": {
            "required": bool(pending or confirmed),
            "pendingSlots": pending,
            "confirmedSlots": confirmed,
        },
        "sourceTemplateId": job.get("templateId") or "",
        "replacementJobId": job.get("id") or "",
        "importedFromXhsNoteReplacement": True,
    }

def publish_feature_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    return str(env.get(PUBLISH_FEATURE_ENV, "1")).strip().lower() not in ("0", "false", "no", "off")


def normalize_publish_tags(tags) -> list[str]:
    if isinstance(tags, str):
        raw = re.split(r"[,，\s]+", tags)
    elif isinstance(tags, (list, tuple, set)):
        raw = list(tags)
    else:
        raw = []
    out = []
    seen = set()
    for item in raw:
        text = str(item or "").strip()
        if not text:
            continue
        text = re.sub(r"^#+", "", text).strip()
        text = re.sub(r"\s+", "", text)
        if not text:
            continue
        tag = "#" + text
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return out


def image_note_publish_blocker(material: dict) -> str:
    material = material or {}
    if material.get("type") != "image_note":
        return ""
    if str(material.get("platform") or "").strip().lower() != "xhs":
        return "xhs_note_platform_unsupported"
    files = [item for item in (material.get("files") or []) if str(item or "").strip()]
    if not files:
        return "no_files"
    if len(files) > 18:
        return "xhs_note_too_many_images"
    review = material.get("aiImageReview") or {}
    if review.get("required") and (
        review.get("pendingSlots") or not review.get("confirmedSlots")
    ):
        return "xhs_note_ai_image_unconfirmed"
    return ""


def apply_publish_result(material: dict, result: dict, account_id: str, dry_run: bool, error_id: str = "") -> dict:
    material = dict(material or {})
    result = result or {}
    now_ts = time.time()
    publish_record = {
        "platform": "xhs",
        "accountId": account_id or "",
        "dryRun": bool(dry_run),
        "finalUrl": result.get("final_url") or result.get("finalUrl") or "",
        "error": result.get("error") or "",
        "filled": bool(result.get("filled")),
        "published": bool(result.get("published")),
        "updatedAt": now_ts,
    }
    if error_id:
        publish_record["errorId"] = error_id
    material["publishResult"] = publish_record
    if result.get("ok") and result.get("published") and not dry_run:
        material["status"] = "published"
        material["published"] = 1
        material["publishedAt"] = now_ts
    elif result.get("ok") or result.get("filled"):
        material["status"] = material.get("status") or "draft"
        material["published"] = int(material.get("published") or 0)
    else:
        material["status"] = "publish_failed"
        material["published"] = int(material.get("published") or 0)
        material["publishError"] = {
            "error": result.get("error") or "publish_failed",
            "errorId": error_id or result.get("errorId") or "",
            "stage": "xhs_publish",
        }
    return material

def smoke_four_image_replacement(material: Optional[dict] = None,
                                 business_input: Optional[dict] = None,
                                 provided_assets: Optional[list[dict]] = None) -> dict:
    """Run a side-effect-free four-image XHS note replacement smoke path."""
    material = material or {
        "id": "mat-smoke-xhs-4",
        "type": "image",
        "platform": "xhs",
        "title": "\u539f\u59cb\u56fe\u6587\u6807\u9898",
        "body": "\u539f\u59cb\u56fe\u6587\u6b63\u6587",
        "tags": ["#\u5c0f\u7ea2\u4e66", "#\u56fe\u6587"],
        "sourceUrl": "https://www.xiaohongshu.com/explore/smoke-four-image",
        "files": ["01-cover.jpg", "02-product.jpg", "03-detail.jpg", "04-cta.jpg"],
    }
    business_input = business_input or {
        "name": "\u672c\u5730\u95e8\u5e97",
        "region": "\u676d\u5dde",
        "audience": "\u65b0\u5ba2\u6237",
        "sellingPoints": ["\u5230\u5e97\u4f53\u9a8c", "\u9884\u7ea6\u4fbf\u6377"],
    }
    provided_assets = provided_assets or [
        {"slotRole": "cover", "assetId": "as-cover", "filePath": "cover-replace.jpg"},
        {"slotRole": "product", "assetId": "as-product", "filePath": "product-replace.jpg"},
    ]
    template = build_template(material)
    preview = build_replacement_preview(template, business_input, provided_assets)
    job = {
        "id": new_job_id(),
        "status": "preview",
        "templateId": template.get("id"),
        "template": template,
        "businessInput": business_input,
        "slotMappings": preview.get("slotMappings") or [],
        "copyCandidates": preview.get("copyCandidates") or [],
        "selectedCopyIndex": preview.get("selectedCopyIndex") or 0,
        "aiSlotCount": preview.get("aiSlotCount") or 0,
    }
    saved_files = [
        os.path.basename(str(mapping.get("filePath") or ""))
        for mapping in job["slotMappings"]
        if str(mapping.get("filePath") or "").strip()
    ]
    draft = build_draft_material_payload(job, saved_files)
    return {
        "template": template,
        "preview": preview,
        "job": job,
        "draft": draft,
        "publishBlocker": image_note_publish_blocker(draft),
    }
