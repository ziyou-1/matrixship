# -*- coding: utf-8 -*-
"""
matrixship ↔ 漫剧(ai-education)共享主库访问层。

漫剧的 MySQL(ai_education 库)是**唯一主库**:用户/余额(users.computing_power)/
模型价格(model_prices)/资产(asset_library)都在这里。matrixship 中心服通过本模块
读写同一套表,实现账号/余额/价格/资产四互通。matrixship 自己的会话/调度/本机任务/
兑换码仍在它的 JSON。

依赖(matrixship 服务器已具备):pymysql、passlib[bcrypt]。
连接:宿主机 127.0.0.1:3306(漫剧 mysql 容器已把 3306 映射到宿主机)。
配置走 env(systemd drop-in):MAINDB_HOST/PORT/USER/PASS/NAME。
"""
import os
import time
import uuid
import threading
from decimal import Decimal, ROUND_HALF_UP

import pymysql
from passlib.context import CryptContext

_PWD = CryptContext(schemes=["bcrypt"], deprecated="auto")  # 与漫剧 core/security.py 一致
_LOCAL = threading.local()

DB_CFG = {
    "host": os.getenv("MAINDB_HOST", "127.0.0.1"),
    "port": int(os.getenv("MAINDB_PORT", "3306") or 3306),
    "user": os.getenv("MAINDB_USER", "ai_edu_user"),
    "password": os.getenv("MAINDB_PASS", "ai_edu_pass"),
    "database": os.getenv("MAINDB_NAME", "ai_education"),
}


def configured():
    return bool(DB_CFG.get("host") and DB_CFG.get("user") and DB_CFG.get("database"))


def _conn():
    """每线程一个连接(ThreadingHTTPServer 多线程);断线重连。"""
    c = getattr(_LOCAL, "conn", None)
    if c is not None:
        try:
            c.ping(reconnect=True)
            return c
        except Exception:
            try:
                c.close()
            except Exception:
                pass
            _LOCAL.conn = None
    conn = pymysql.connect(
        host=DB_CFG["host"], port=DB_CFG["port"], user=DB_CFG["user"],
        password=DB_CFG["password"], database=DB_CFG["database"],
        charset="utf8mb4", autocommit=True, connect_timeout=8, read_timeout=15, write_timeout=15,
        cursorclass=pymysql.cursors.DictCursor,
    )
    _LOCAL.conn = conn
    return conn


def _q(sql, args=None, one=False):
    conn = _conn()
    with conn.cursor() as cur:
        cur.execute(sql, args or ())
        if one:
            return cur.fetchone()
        return cur.fetchall()


def _exec(sql, args=None):
    conn = _conn()
    with conn.cursor() as cur:
        cur.execute(sql, args or ())
        return cur.lastrowid, cur.rowcount


def ping():
    try:
        return bool(_q("SELECT 1 AS ok", one=True))
    except Exception:
        return False


# ---------------- 用户 / 认证 ----------------
_USER_COLS = "id, phone, email, username, password_hash, member_level, member_plan_id, computing_power, is_active, is_admin, is_staff"


def get_user_by_id(uid):
    try:
        return _q("SELECT %s FROM users WHERE id=%%s" % _USER_COLS, (int(uid),), one=True)
    except Exception:
        return None


def get_user_by_phone(phone):
    p = str(phone or "").strip()
    if not p:
        return None
    return _q("SELECT %s FROM users WHERE phone=%%s LIMIT 1" % _USER_COLS, (p,), one=True)


def find_login_user(identifier):
    """按 手机/邮箱/用户名/id 找登录用户(与漫剧登录标识一致)。"""
    ident = str(identifier or "").strip()
    if not ident:
        return None
    row = _q("SELECT %s FROM users WHERE phone=%%s OR email=%%s OR username=%%s LIMIT 1" % _USER_COLS,
             (ident, ident, ident), one=True)
    if row:
        return row
    if ident.isdigit():
        return get_user_by_id(ident)
    return None


def verify_password(user, password):
    h = (user or {}).get("password_hash")
    if not h:
        return False
    try:
        return _PWD.verify(password or "", h)
    except Exception:
        return False


def hash_password(password):
    return _PWD.hash(password or "")


def set_password(uid, password):
    _exec("UPDATE users SET password_hash=%s, updated_at=NOW() WHERE id=%s", (hash_password(password), int(uid)))


def set_username(uid, name):
    if not name:
        return
    _exec("UPDATE users SET username=%s, updated_at=NOW() WHERE id=%s", (str(name)[:40], int(uid)))


def create_phone_user(phone, password=None, signup_bonus=0):
    """按手机号建漫剧用户(注册)。返回新用户 dict。已存在则返回已有(不覆盖密码)。"""
    p = str(phone or "").strip()
    existing = get_user_by_phone(p)
    if existing:
        return existing
    ph = hash_password(password) if password else None
    _exec("INSERT INTO users (phone, password_hash, member_level, computing_power, is_active, is_verified, created_at, updated_at) "
          "VALUES (%s, %s, 'FREE', %s, 1, 1, NOW(), NOW())",
          (p, ph, str(signup_bonus or 0)))
    return get_user_by_phone(p)


# ---------------- 余额(computing_power)----------------
def get_balance(uid):
    u = get_user_by_id(uid)
    if not u:
        return 0.0
    return float(u.get("computing_power") or 0)


def _to_dec(x):
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal("0")


# ---------------- 模型价格(model_prices)----------------
def get_model_price(model_id):
    """返回该模型的 {price_per_call, input_token_price, output_token_price, billing_method, model_type} 或 None。"""
    if not model_id:
        return None
    return _q("SELECT model_id, model_type, billing_method, price_per_call, input_token_price, output_token_price, enabled "
              "FROM model_prices WHERE model_id=%s AND enabled=1 LIMIT 1", (str(model_id),), one=True)


def _est_tokens(params):
    """从生成参数里估算 token 数(用于 per_token 类如 TTS 计费)。中文近似 1 字≈1 token。"""
    p = params or {}
    text = (p.get("prompt") or p.get("text") or p.get("content")
            or p.get("input") or p.get("tts_text") or "")
    n = len(str(text))
    return max(n, 50)  # 给最小值,避免极短文本 0 扣白嫖


def price_for(model_id, params=None):
    """按模型算这次生成应扣的算力。返回 Decimal。
    - per_call:直接取 price_per_call(图/视频,如 gpt-image-2=0.0528、kling-avatar=0.396)。
    - per_token:price_per_call/output_token_price 是**每百万 token**单价,按估算 token 数换算,
      避免把 396(每百万)当成单次直接扣爆余额。"""
    row = get_model_price(model_id)
    if not row:
        return None
    method = str(row.get("billing_method") or "per_call")
    if method == "per_token":
        rate = _to_dec(row.get("output_token_price")) or _to_dec(row.get("price_per_call"))
        amt = rate * Decimal(_est_tokens(params)) / Decimal(1000000)
        # 保底:再短也别 0 扣(防白嫖),给个极小下限
        return max(amt, Decimal("0.001"))
    return _to_dec(row.get("price_per_call"))


# ---------------- 扣费 / 退款(照漫剧:扣 computing_power + 写 model_usage_logs)----------------
def charge_generation(uid, model_id, params=None, request_id=None, project_id=None, task_id=None, multiplier=1.0):
    """按 model_prices 给用户扣算力,并写 model_usage_logs。原子(事务+条件扣费防超扣)。
    multiplier:matrixship 在漫剧成本价基础上的加价倍率(漫剧画布自己扣费时 multiplier=1,不受影响)。
    返回 (ok, amount(float), balance_after(float), error)。amount<=0 的模型放行不扣。"""
    row = get_model_price(model_id)
    if row is None:
        return False, 0.0, get_balance(uid), "该模型未在 model_prices 配置"
    base = price_for(model_id, params)
    if base is None:
        return False, 0.0, get_balance(uid), "该模型未在 model_prices 配置"
    try:
        mult = Decimal(str(multiplier or 1))
    except Exception:
        mult = Decimal("1")
    if mult <= 0:
        mult = Decimal("1")
    amt = (base * mult).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    rid = request_id or ("msgen-" + uuid.uuid4().hex)
    if amt <= 0:
        return True, 0.0, get_balance(uid), None
    conn = _conn()
    try:
        conn.begin()  # 显式事务:扣费 + 写流水原子提交(任一失败整体回滚)
        with conn.cursor() as cur:
            # 条件扣费:余额足够才扣,原子防并发超扣
            cur.execute("UPDATE users SET computing_power = computing_power - %s, updated_at=NOW() "
                        "WHERE id=%s AND computing_power >= %s", (str(amt), int(uid), str(amt)))
            if cur.rowcount != 1:
                conn.rollback()
                return False, float(amt), get_balance(uid), "insufficient_balance"
            cur.execute("SELECT computing_power FROM users WHERE id=%s", (int(uid),))
            bal_after = float((cur.fetchone() or {}).get("computing_power") or 0)
            cur.execute(
                "INSERT INTO model_usage_logs (request_id, user_id, project_id, task_id, model_id, model_type, "
                "billing_method, amount, balance_before, balance_after, status, description, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'success',%s,NOW())",
                (rid, int(uid), project_id, task_id, str(model_id), row.get("model_type") or "media",
                 row.get("billing_method") or "per_call", str(amt), str(bal_after + float(amt)), str(bal_after),
                 "matrixship 生成扣费(成本 %s ×%s)" % (base, mult)))
        conn.commit()
        return True, float(amt), bal_after, None
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return False, float(amt), get_balance(uid), str(e)[:120]


def refund_generation(request_id, reason=""):
    """按 request_id 退款:找 success 且未退的流水 → 加回 computing_power + 标 refunded。幂等。
    返回 (ok, amount)。"""
    if not request_id:
        return False, 0.0
    conn = _conn()
    try:
        conn.begin()  # 事务:认领(success→refunded)+ 加回算力原子提交
        with conn.cursor() as cur:
            cur.execute("SELECT id, user_id, amount, status, refunded_at FROM model_usage_logs WHERE request_id=%s LIMIT 1",
                        (str(request_id),))
            log = cur.fetchone()
            if not log or log.get("refunded_at") or str(log.get("status")) == "refunded":
                conn.rollback()
                return False, 0.0
            amt = _to_dec(log.get("amount"))
            # 先原子认领退款:只有把 status success→refunded 成功(rowcount==1)的调用才继续退款,
            # 防并发/重复退导致多次加回算力(幂等)。description 后缀作为绑定参数传,不嵌进 SQL 字面量。
            cur.execute("UPDATE model_usage_logs SET status='refunded', refunded_at=NOW(), "
                        "description=CONCAT(COALESCE(description,''), %s) "
                        "WHERE id=%s AND status<>'refunded' AND refunded_at IS NULL",
                        (" | 退款:" + (reason or ""), log["id"]))
            if cur.rowcount != 1:
                conn.rollback()
                return False, 0.0
            if amt > 0:
                cur.execute("UPDATE users SET computing_power = computing_power + %s, updated_at=NOW() WHERE id=%s",
                            (str(amt), int(log["user_id"])))
        conn.commit()
        return True, float(amt)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise


def topup(uid, amount, reason="充值"):
    """给用户加算力(充值/兑换/管理员)。返回 (ok, balance_after)。"""
    amt = _to_dec(amount)
    if amt <= 0:
        return False, get_balance(uid)
    try:
        _lastrowid, rowcount = _exec(
            "UPDATE users SET computing_power = computing_power + %s, updated_at=NOW() WHERE id=%s",
            (str(amt), int(uid)),
        )
        if rowcount != 1:
            return False, get_balance(uid)
        return True, get_balance(uid)
    except Exception:
        return False, get_balance(uid)


def list_model_usage_logs(uid, start_at, end_at, limit=50001):
    safe_limit = max(1, min(int(limit), 50001))
    sql = (
        "SELECT id, request_id, user_id, project_id, task_id, model_id, model_type, "
        "billing_method, amount, balance_before, balance_after, status, description, "
        "created_at, refunded_at FROM model_usage_logs "
        "WHERE user_id=%s AND created_at >= %s AND created_at < %s "
        "ORDER BY created_at DESC, id DESC LIMIT %s"
    )
    return _q(sql, (int(uid), start_at, end_at, safe_limit))


# ---------------- 资产库(asset_library)----------------
def list_assets(uid, limit=200, asset_type=None):
    try:
        if asset_type:
            return _q("SELECT id, asset_type, name, description, thumbnail_url, asset_data, tags, category, status, source_type, created_at "
                      "FROM asset_library WHERE user_id=%s AND asset_type=%s AND (status IS NULL OR status<>'archived') ORDER BY id DESC LIMIT %s",
                      (int(uid), str(asset_type), int(limit)))
        return _q("SELECT id, asset_type, name, description, thumbnail_url, asset_data, tags, category, status, source_type, created_at "
                  "FROM asset_library WHERE user_id=%s AND (status IS NULL OR status<>'archived') ORDER BY id DESC LIMIT %s",
                  (int(uid), int(limit)))
    except Exception:
        return []


def add_asset(uid, asset_type, name, asset_data=None, thumbnail_url=None, description=None, source_type="matrixship"):
    import json as _json
    try:
        rid, _ = _exec(
            "INSERT INTO asset_library (user_id, asset_type, name, description, thumbnail_url, asset_data, tags, status, source_type, created_at, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'active',%s,NOW(),NOW())",
            (int(uid), asset_type or "prop", name or "素材", description, thumbnail_url,
             _json.dumps(asset_data or {}, ensure_ascii=False), _json.dumps([], ensure_ascii=False), source_type))
        return rid
    except Exception:
        return None
