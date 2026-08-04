import copy
import hashlib
import json
import os
import shutil
import time
import uuid
from urllib.parse import urlparse


def _path_hash(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _safe_url_parts(value):
    raw = str(value or "").strip()
    if not raw:
        return {}
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return {}
    host = parsed.hostname or ""
    if parsed.port:
        host = "%s:%s" % (host, parsed.port)
    return {
        "scheme": parsed.scheme,
        "host": host,
        "pathHash": _path_hash(parsed.path or "/"),
    }


def _analysis_duration(analysis):
    meta = analysis.get("meta") if isinstance(analysis, dict) else {}
    try:
        return float((meta or {}).get("duration") or 0)
    except (TypeError, ValueError):
        return 0.0


class ReplacementAnalysis:
    def __init__(
            self,
            downloader=None,
            download_validator=None,
            platform_from_url=None,
            source_validator=None,
            frame_extractor=None,
            ocr_runner=None,
            transcription_runner=None,
            vision_runner=None,
            report_builder=None,
            markdown_builder=None,
            image_data_url=None,
            json_logger=None,
            log_event=None,
            work_root=None):
        self.downloader = downloader
        self.download_validator = download_validator or (lambda _path: {"ok": True})
        self.platform_from_url = platform_from_url or (lambda _url: "")
        self.source_validator = source_validator or (lambda _path: {"ok": True})
        self.frame_extractor = frame_extractor or (lambda _video_path, _frames_dir, _limit: [])
        self.ocr_runner = ocr_runner or (lambda _frames: {
            "status": "disabled",
            "engine": "none",
            "text": "",
            "errors": [],
        })
        self.transcription_runner = transcription_runner or (lambda _video_path, out_dir, progress=None: {
            "status": "disabled",
            "text": "",
            "segments": [],
            "failedRanges": [],
            "errors": [],
            "retryCount": 0,
            "outDir": out_dir,
        })
        self.vision_runner = vision_runner or (lambda _prompt, _frame_urls, **_kwargs: "")
        self.report_builder = report_builder or (lambda out: (out.get("report") or "", "分析完成"))
        self.markdown_builder = markdown_builder or (lambda out: out.get("report") or "")
        self.image_data_url = image_data_url or (lambda _path: "")
        self.json_logger = json_logger or (lambda *_args, **_kwargs: '{"errorId":"-"}')
        self.log_event = log_event or (lambda *_args, **_kwargs: None)
        self.work_root = work_root or self._default_work_root

    def resolve_source(self, request, job_dir, progress=None):
        request = request if isinstance(request, dict) else {}
        job_dir = os.path.abspath(str(job_dir or ""))
        os.makedirs(job_dir, exist_ok=True)

        handoff = request.get("handoff") if isinstance(request.get("handoff"), dict) else None
        if handoff is None and request.get("sourceVideoPath"):
            handoff = request
        if self._valid_handoff_video(handoff):
            return self._resolved_payload(
                source_url=handoff.get("sourceUrl") or handoff.get("url") or "",
                platform=handoff.get("platform") or "",
                source_video_path=handoff.get("sourceVideoPath") or "",
                analysis=handoff.get("breakdownAnalysis") or {},
                handoff_id=handoff.get("handoffId") or handoff.get("id") or "",
            )

        source_url = str(request.get("sourceUrl") or "").strip()
        if not source_url:
            raise ValueError("replacement_source_required")
        if self.downloader is None or not hasattr(self.downloader, "download"):
            raise RuntimeError("replacement_source_downloader_missing")

        platform = str(self.platform_from_url(source_url) or request.get("platform") or "").strip()
        source_video_path = os.path.abspath(self.downloader.download(source_url, job_dir))
        validation = copy.deepcopy(self.download_validator(source_video_path) or {})
        if not validation.get("ok"):
            self._cleanup_invalid_source(source_video_path, job_dir)
            analysis = self._invalid_analysis(
                source_video_path,
                source_url,
                platform,
                validation,
                "参考视频分析失败（视频文件无效）",
            )
            return self._failed_payload(source_url, platform, source_video_path, analysis)

        result = self.analyze(
            source_video_path,
            source_url=source_url,
            platform=platform,
            out_dir=os.path.join(job_dir, "analysis"),
            progress=progress,
        )
        analysis = copy.deepcopy((result or {}).get("analysis") or {})
        analysis_validation = analysis.get("validation") if isinstance(analysis.get("validation"), dict) else {}
        if analysis_validation.get("ok") is False:
            return self._failed_payload(source_url, platform, source_video_path, analysis)
        return self._resolved_payload(
            source_url=source_url,
            platform=platform,
            source_video_path=source_video_path,
            analysis=analysis,
            message=(result or {}).get("message") or "",
        )

    def analyze(self, video_path, source_url="", platform="", out_dir="", progress=None):
        video_path = os.path.abspath(str(video_path or "").strip())
        source_url = str(source_url or "").strip()
        platform = str(platform or "").strip()
        out = {
            "platform": platform,
            "sourceUrl": source_url,
            "videoPath": video_path,
        }
        tmp_root = os.path.abspath(out_dir or self.work_root())
        os.makedirs(tmp_root, exist_ok=True)

        def notify(message):
            if callable(progress):
                progress(str(message or ""))

        self.log_event(
            "reference_analysis_started",
            video=os.path.basename(video_path),
            source_url=source_url,
            platform=platform,
        )
        try:
            notify("校验参考视频…")
            validation = copy.deepcopy(self.source_validator(video_path) or {})
            out["validation"] = validation
            if not validation.get("ok"):
                failed = self._invalid_analysis(
                    video_path,
                    source_url,
                    platform,
                    validation,
                    "参考视频分析失败（视频文件无效）",
                )
                return {
                    "analysis": failed,
                    "markdown": self.markdown_builder(failed),
                    "message": "参考视频分析失败（视频文件无效）",
                }

            out["meta"] = {
                "duration": validation.get("duration") or 0,
                "width": validation.get("width") or 0,
                "height": validation.get("height") or 0,
                "path": video_path,
            }
            notify("抽取整条视频关键帧…")
            frames = self.frame_extractor(video_path, os.path.join(tmp_root, "frames"), 16) or []
            out["frameNotes"] = "\n".join(
                "[%.2fs] %s" % (frame.get("time") or 0, os.path.basename(frame.get("path") or ""))
                for frame in frames
            ) or "未抽取到关键帧"

            notify("识别画面字幕…")
            out["ocr"] = copy.deepcopy(self.ocr_runner(frames) or {})

            notify("分片转写整条视频口播…")
            out["transcript"] = copy.deepcopy(self.transcription_runner(
                video_path,
                os.path.join(tmp_root, "audio"),
                progress=progress,
            ) or {})
            out["transcript"].setdefault("retryCount", 0)

            notify("调用视觉模型分析关键帧…")
            frame_urls = [self.image_data_url(frame.get("path")) for frame in frames[:16]]
            frame_urls = [url for url in frame_urls if url]
            if frame_urls:
                try:
                    out["visual"] = self.vision_runner(
                        "请逐帧深度描述这些短视频关键帧，严格按时间顺序提取人物外观、构图、景别、动作、产品/道具、场景、字幕和镜头节奏；不要臆造关键帧中看不到的内容。",
                        frame_urls,
                        max_tokens=2200,
                        billing_scenario="video_breakdown",
                        billing_stage="visual_analysis",
                        billing_detail="workflow assistant key frame visual analysis",
                    )
                except Exception as exc:
                    error_id = self._log_error(
                        "workflow_reference_vision_failed",
                        exc=exc,
                        code="workflow_reference_vision_failed",
                        video_path=video_path,
                    )
                    out["visual"] = "视觉模型分析失败（errorId: %s）: %s\n%s" % (
                        error_id or "-",
                        str(exc)[:160],
                        out.get("frameNotes") or "",
                    )
            else:
                out["visual"] = "未抽取到可供视觉模型分析的关键帧。"

            notify("生成完整拆解报告…")
            report, message = self.report_builder(out)
            out["report"] = report
            markdown = self.markdown_builder(out)
            self.log_event(
                "reference_analysis_completed",
                video=os.path.basename(video_path),
                duration=(out.get("meta") or {}).get("duration") or 0,
                transcript_status=(out.get("transcript") or {}).get("status") or "",
                transcript_segments=len((out.get("transcript") or {}).get("segments") or []),
                report_chars=len(report or ""),
            )
            return {
                "analysis": out,
                "markdown": markdown,
                "message": message or "分析完成",
            }
        except Exception as exc:
            error_id = self._log_error(
                "workflow_reference_analysis_failed",
                exc=exc,
                code="workflow_reference_analysis_failed",
                video_path=video_path,
            )
            out["meta"] = out.get("meta") or {}
            out["ocr"] = out.get("ocr") or {
                "status": "failed",
                "engine": "none",
                "text": "",
                "errors": [],
                "message": str(exc)[:160],
            }
            out["transcript"] = out.get("transcript") or self._diagnostic_transcript(str(exc))
            out["report"] = "## 分解失败\nerrorId: %s\n\n%s" % (error_id or "-", str(exc)[:500])
            return {
                "analysis": out,
                "markdown": self.markdown_builder(out),
                "message": "参考视频分析失败（错误编号 %s）" % (error_id or "-"),
            }
        finally:
            if not out_dir:
                shutil.rmtree(tmp_root, ignore_errors=True)

    def _valid_handoff_video(self, handoff):
        if not isinstance(handoff, dict):
            return False
        source_video_path = str(handoff.get("sourceVideoPath") or "").strip()
        return bool(source_video_path and os.path.isfile(source_video_path))

    def _invalid_analysis(self, video_path, source_url, platform, validation, message):
        validation = copy.deepcopy(validation or {})
        return {
            "platform": str(platform or "").strip(),
            "sourceUrl": str(source_url or "").strip(),
            "videoPath": os.path.abspath(str(video_path or "").strip()),
            "validation": validation,
            "meta": validation,
            "ocr": {
                "status": "skipped",
                "engine": "none",
                "text": "",
                "errors": [],
                "message": "视频真实性校验未通过。",
            },
            "transcript": self._diagnostic_transcript("视频真实性校验未通过。"),
            "visual": "",
            "report": (
                "## 分解失败\n"
                "源视频未通过真实性校验，未把不可验证内容交给同款替换。\n\n"
                "- code: %s"
            ) % (validation.get("code") or "media_invalid"),
            "error": validation.get("code") or "media_invalid",
            "message": str(message or "")[:160],
        }

    def _diagnostic_transcript(self, message):
        return {
            "status": "failed",
            "code": "workflow_reference_analysis_failed",
            "text": "",
            "segments": [],
            "failedRanges": [],
            "errors": [],
            "message": str(message or "")[:240],
        }

    def _resolved_payload(self, source_url, platform, source_video_path, analysis, handoff_id="", message=""):
        source_url = str(source_url or "").strip()
        platform = str(platform or "").strip()
        source_video_path = os.path.abspath(str(source_video_path or "").strip())
        analysis = copy.deepcopy(analysis or {})
        return {
            "status": "ok",
            "error": "",
            "message": str(message or ""),
            "handoffId": str(handoff_id or "").strip(),
            "platform": platform,
            "sourceUrl": source_url,
            "source": _safe_url_parts(source_url),
            "sourceVideoPath": source_video_path,
            "breakdownAnalysis": analysis,
            "sourceContext": {
                "handoffId": str(handoff_id or "").strip(),
                "platform": platform,
                "duration": _analysis_duration(analysis),
                "hasBreakdownAnalysis": bool(analysis),
                "sourceVideoAvailable": bool(source_video_path and os.path.isfile(source_video_path)),
                "sourceVideoPathHash": _path_hash(source_video_path),
            },
        }

    def _failed_payload(self, source_url, platform, source_video_path, analysis):
        resolved = self._resolved_payload(
            source_url=source_url,
            platform=platform,
            source_video_path=source_video_path,
            analysis=analysis,
            message=(analysis or {}).get("message") or "",
        )
        resolved["status"] = "failed"
        resolved["error"] = (
            ((analysis or {}).get("validation") or {}).get("code")
            or (analysis or {}).get("error")
            or "media_invalid"
        )
        resolved["sourceContext"]["sourceVideoAvailable"] = False
        return resolved

    def _cleanup_invalid_source(self, source_video_path, job_dir):
        source_video_path = os.path.abspath(str(source_video_path or "").strip())
        job_dir = os.path.abspath(str(job_dir or "").strip())
        if not (source_video_path and job_dir):
            return
        if source_video_path != job_dir and not source_video_path.startswith(job_dir + os.sep):
            return
        if os.path.isfile(source_video_path):
            try:
                os.remove(source_video_path)
            except OSError:
                pass

    def _log_error(self, event, **fields):
        raw = self.json_logger(event, **fields)
        try:
            payload = json.loads(raw or "{}")
        except Exception:
            payload = {}
        return str(payload.get("errorId") or "-")

    def _default_work_root(self):
        return os.path.abspath(
            os.path.join(os.getcwd(), "output", "replacement-analysis-" + uuid.uuid4().hex)
        )
