"""从 LK888 抓全量模型表单 schema,生成随包快照与测试 fixture。

产物:
  backend/lk888_schema_snapshot.py       随包快照(gzip+base64 单常量,PyInstaller 靠 import 自动收集)
  tests/fixtures/lk888_model_schemas.json 测试 fixture(明文,便于 diff review)

用法:
  .venv-win\\Scripts\\python.exe tools/gen_lk888_schema_snapshot.py            # 联网重抓
  .venv-win\\Scripts\\python.exe tools/gen_lk888_schema_snapshot.py <已抓好的.json>

快照只是兜底:客户端运行时优先用 GET /lk888/v1/skills/models/{name} 的实时结果。
上游新增模型或改参数后重跑本脚本刷新快照即可,不需要改客户端代码。
"""
import base64
import gzip
import io
import json
import os
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT_PY = os.path.join(ROOT, "backend", "lk888_schema_snapshot.py")
FIXTURE_JSON = os.path.join(ROOT, "tests", "fixtures", "lk888_model_schemas.json")
BASE = os.environ.get("LK888_BASE_URL", "https://api.lk888.ai").rstrip("/") + "/api"


def _api_key():
    key = os.environ.get("LK888_API_KEY", "").strip()
    if key:
        return key
    env = os.path.join(ROOT, "backend", ".env")
    if os.path.isfile(env):
        for line in io.open(env, encoding="utf-8-sig"):
            if line.startswith("LK888_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("找不到 LK888_API_KEY:设环境变量或写进 backend/.env")


def _get(path, key):
    req = urllib.request.Request(BASE + path, headers={"Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_all():
    key = _api_key()
    names = []
    for kind in ("image", "video"):
        payload = _get("/v1/skills/models?type=" + kind, key)
        rows = payload if isinstance(payload, list) else (payload.get("models") or payload.get("data") or [])
        names.extend(str(r.get("name")) for r in rows if r.get("name"))
    print("模型数:%d" % len(names))

    def one(name):
        try:
            return name, _get("/v1/skills/models/" + urllib.parse.quote(name, safe=""), key)
        except Exception as e:
            print("  跳过 %s: %s" % (name, str(e)[:80]))
            return name, None

    with ThreadPoolExecutor(max_workers=8) as ex:
        return {n: s for n, s in ex.map(one, names) if isinstance(s, dict) and s.get("params")}


def trim(schemas):
    """快照只留渲染表单必需的字段。description 保留(它是要显示给用户的填写依据),
    但模型 description(营销长文)丢掉 —— 参数区不显示它。"""
    out = {}
    for name, raw in sorted(schemas.items()):
        params = []
        for p in raw.get("params") or []:
            row = {
                "name": str(p.get("name") or ""),
                "label": str(p.get("label") or ""),
                "type": str(p.get("type") or "").lower(),
                "required": bool(p.get("required")),
                "description": str(p.get("description") or ""),
            }
            opts = p.get("options")
            if isinstance(opts, list) and opts:
                row["options"] = [
                    {"value": str(o.get("value")), "label": str(o.get("label") or o.get("value"))}
                    for o in opts if isinstance(o, dict) and o.get("value") is not None
                ]
            if row["name"]:
                params.append(row)
        out[name] = {
            "name": name,
            "display_name": str(raw.get("display_name") or ""),
            "input_hint": str(raw.get("input_hint") or ""),
            "type": str(raw.get("type") or "").lower(),
            "tags": [str(t) for t in (raw.get("tags") or [])],
            "params": params,
        }
    return out


def write_snapshot(schemas):
    blob = json.dumps(schemas, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    packed = base64.b64encode(gzip.compress(blob, 9)).decode("ascii")
    lines = [packed[i:i + 96] for i in range(0, len(packed), 96)]
    body = '"\n    "'.join(lines)
    src = '''"""LK888 模型表单 schema 随包快照 —— 由 tools/gen_lk888_schema_snapshot.py 生成,不要手改。

Agent.模式按每个模型自己的 params 渲染参数控件。运行时优先取 GET /lk888/v1/skills/models/{name},
本快照只在首次冷启动、断网或上游不可用时兜底,保证参数区不会退回「所有模型一个样」。
模型数:%d
"""
import base64
import gzip
import json

_PACKED = (
    "%s"
)

_CACHE = None


def all_schemas():
    global _CACHE
    if _CACHE is None:
        _CACHE = json.loads(gzip.decompress(base64.b64decode(_PACKED)).decode("utf-8"))
    return _CACHE


def schema_for(name):
    return all_schemas().get(str(name or ""))
''' % (len(schemas), body)
    with io.open(SNAPSHOT_PY, "w", encoding="utf-8", newline="\n") as f:
        f.write(src)
    print("写入 %s (%.1f KB)" % (SNAPSHOT_PY, os.path.getsize(SNAPSHOT_PY) / 1024.0))


def write_fixture(schemas):
    os.makedirs(os.path.dirname(FIXTURE_JSON), exist_ok=True)
    with io.open(FIXTURE_JSON, "w", encoding="utf-8", newline="\n") as f:
        json.dump(schemas, f, ensure_ascii=False, indent=1, sort_keys=True)
    print("写入 %s (%.1f KB)" % (FIXTURE_JSON, os.path.getsize(FIXTURE_JSON) / 1024.0))


def main():
    if len(sys.argv) > 1:
        raw = json.load(io.open(sys.argv[1], encoding="utf-8"))
    else:
        raw = fetch_all()
    schemas = trim(raw)
    if len(schemas) < 20:
        raise SystemExit("只拿到 %d 个模型,拒绝用这份结果覆盖快照" % len(schemas))
    write_snapshot(schemas)
    write_fixture(schemas)
    kinds = {}
    for s in schemas.values():
        for p in s["params"]:
            kinds[p["type"]] = kinds.get(p["type"], 0) + 1
    print("参数控件类型分布:", dict(sorted(kinds.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
