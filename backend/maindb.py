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


class PasswordBackendError(RuntimeError):
    """bcrypt/passlib 后端本身失效,而不是密码不匹配。

    调用方必须把它当成服务端故障上报,**绝不能**降级成"凭据错误"。2026-08-05
    的事故就是这么来的:镜像重建把 bcrypt 拉到 5.0.0,和 passlib 1.7.4 不兼容,
    每次校验都抛 ValueError,旧实现把异常吞成 False,于是所有漫剧账号在登录页
    看到的都是 invalid_credentials。
    """


def verify_password(user, password):
    h = (user or {}).get("password_hash")
    if not h:
        return False
    try:
        return _PWD.verify(password or "", h)
    except Exception as exc:
        # 只带异常类名:passlib 的原始消息可能包含哈希片段。
        raise PasswordBackendError(type(exc).__name__) from exc


def hash_password(password):
    try:
        return _PWD.hash(password or "")
    except Exception as exc:
        raise PasswordBackendError(type(exc).__name__) from exc


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


def get_balance_strict(uid):
    """Read the current balance without converting query failures to zero."""
    user = _q(
        "SELECT computing_power FROM users WHERE id=%s LIMIT 1",
        (int(uid),),
        one=True,
    )
    if not user:
        return 0.0
    return float(user.get("computing_power") or 0)


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
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'charged',%s,NOW())",  # 'charged' 是漫剧平台在用的值
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


_POWER_RECORDS_OK = None


def _power_records_available():
    """computing_power_records 是否可写。只探一次并缓存;**不能**放进扣费事务里探,
    否则探测失败会连累整笔扣费回滚。"""
    global _POWER_RECORDS_OK
    if _POWER_RECORDS_OK is None:
        try:
            _q("SELECT 1 FROM computing_power_records LIMIT 1")
            _POWER_RECORDS_OK = True
        except Exception:
            _POWER_RECORDS_OK = False
    return _POWER_RECORDS_OK


def charge_actual_cost(uid, amount_power, request_id, model_id="", description="",
                       project_id=None, task_id=None, model_type="media",
                       billing_method="per_call", allow_arrears=False):
    """按**实际成本**扣算力,并在同一事务内写 model_usage_logs + computing_power_records。

    与 charge_generation() 的唯一区别是金额来源:这里由调用方给出(LK888 返回的真实消费),
    不查 model_prices —— 上游随时新增模型,价格表必然覆盖不全,而真实成本永远可得。
    其余一律对齐漫剧侧:同一事务、条件扣费、request_id 幂等、退款走 refund_generation()。

    返回 (status, amount, balance_after, error)。
    status ∈ {"charged", "duplicate", "insufficient", "error"}。

    **语句顺序是有意的**:先 model_usage_logs 再 users,与 refund_generation() 完全一致
    (它也是先 SELECT/UPDATE 流水再 UPDATE users)。反过来写会与并发退款形成死锁环。
    """
    if not request_id:
        return "error", 0.0, get_balance(uid), "missing_request_id"
    try:
        amt = _to_dec(amount_power).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    except Exception:
        return "error", 0.0, get_balance(uid), "amount_invalid"
    if amt <= 0:
        return "charged", 0.0, get_balance(uid), None

    conn = _conn()
    try:
        conn.begin()
        with conn.cursor() as cur:
            # 1) 先占坑。request_id 上有唯一索引,重复结算在这里被数据库直接挡下 ——
            #    幂等由数据库保证,不依赖任何进程内状态。
            #    status 直接写终态:未提交的行别人读不到,另造中间态反而可能撞上 ENUM。
            try:
                # status 必须写 'charged':这是漫剧平台自己在用的值(线上 2533 条),
                # 它的消费账单界面按这个口径展示。charge_generation() 里写的 'success'
                # 在线上是 0 条 —— 那个函数从未真正跑过,所以错误值一直没暴露。
                cur.execute(
                    "INSERT INTO model_usage_logs (request_id, user_id, project_id, task_id, model_id, "
                    "model_type, billing_method, amount, balance_before, balance_after, status, "
                    "description, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,0,0,'charged',%s,NOW())",
                    (str(request_id), int(uid), project_id, task_id, str(model_id or ""),
                     str(model_type or "media"), str(billing_method or "per_call"), str(amt),
                     str(description or "matrixship 实际成本扣费")))
            except pymysql.err.IntegrityError as exc:
                conn.rollback()
                # **只有** 1062(唯一键冲突)才是"这笔已经扣过"。其余完整性错误必须报错:
                # task_id/project_id 是指向 generation_tasks / comic_drama_projects 的外键,
                # 传入非法值会报 1452,若一并当成 duplicate,调用方会以为已扣费而放行 ——
                # 用户白嫖,且没有任何记录。
                code = exc.args[0] if exc.args else 0
                if code == 1062:
                    return "duplicate", 0.0, get_balance(uid), None
                return "error", float(amt), get_balance(uid), "integrity_error_%s" % code
            log_id = cur.lastrowid

            # 2) 锁住余额行再判断,避免并发下两笔都通过校验
            cur.execute("SELECT computing_power FROM users WHERE id=%s FOR UPDATE", (int(uid),))
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return "error", float(amt), 0.0, "user_not_found"
            bal_before = _to_dec(row.get("computing_power"))

            if not allow_arrears and bal_before < amt:
                conn.rollback()
                return "insufficient", float(amt), float(bal_before), "insufficient_balance"

            bal_after = bal_before - amt
            # 持有行锁,直接赋绝对值:保证写进流水的 balance_after 与库里实际值一致
            cur.execute("UPDATE users SET computing_power=%s, updated_at=NOW() WHERE id=%s",
                        (str(bal_after), int(uid)))
            cur.execute("UPDATE model_usage_logs SET balance_before=%s, balance_after=%s WHERE id=%s",
                        (str(bal_before), str(bal_after), log_id))

            # 3) 余额流水表:漫剧的账单界面读它,不写这张表就等于矩阵侧的消费在那边"隐身"
            if _power_records_available():
                cur.execute(
                    "INSERT INTO computing_power_records (user_id, change_type, amount, balance, "
                    "order_id, description, created_at) VALUES (%s,'consume',%s,%s,NULL,%s,NOW())",
                    (int(uid), str(-amt), str(bal_after),
                     str(description or "matrixship 实际成本扣费")))
        conn.commit()
        return "charged", float(amt), float(bal_after), None
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return "error", float(amt), get_balance(uid), str(e)[:120]


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
    # created_ts / refunded_ts:让数据库直接给出 epoch。
    # pymysql 返回的是不带时区的 datetime,调用方(billing_analytics._timestamp)会把它
    # 当成北京时间,而库里存的是 UTC —— 每条记录因此早 8 小时,与中心服 JSON 账本的
    # 真实 epoch 混排时,新扣费会沉到旧记录下面,账户中心"最新一条"的扣后余额对不上
    # 当前余额。用 UNIX_TIMESTAMP() 由数据库换算,不依赖任何一侧对时区的假设。
    sql = (
        "SELECT id, request_id, user_id, project_id, task_id, model_id, model_type, "
        "billing_method, amount, balance_before, balance_after, status, description, "
        "created_at, refunded_at, UNIX_TIMESTAMP(created_at) AS created_ts, "
        "UNIX_TIMESTAMP(refunded_at) AS refunded_ts FROM model_usage_logs "
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
