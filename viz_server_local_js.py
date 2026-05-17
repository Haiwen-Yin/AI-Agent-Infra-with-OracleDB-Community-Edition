#!/usr/bin/env python3
"""Oracle Memory System v2.0.0 - Web Visualization Server
Author: Haiwen Yin
Features: Login auth, bilingual, entity graph, node/edge details, auto-logout, DB stats
"""

import json
import http.server
import socketserver
import oracledb
import threading
import hashlib
import time as time_module
import os
from urllib.parse import urlparse, parse_qs

oracledb.defaults.fetch_lobs = False

def load_config():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
    config = {
        "server": {"host": "0.0.0.0", "port": 8000, "session_timeout": 300},
        "database": {"user": "openclaw", "password": "hermes", "dsn": "10.10.10.130:1521/openclaw",
                     "pool_min": 2, "pool_max": 5, "pool_increment": 1},
    }
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                fc = json.load(f)
                for s in config:
                    if s in fc:
                        config[s].update(fc[s])
        except Exception as e:
            print(f'Config load warning: {e}')
    env_map = {
        'MEMORY_DB_USER': ('database', 'user'), 'MEMORY_DB_PASSWORD': ('database', 'password'),
        'MEMORY_DB_DSN': ('database', 'dsn'), 'MEMORY_SERVER_PORT': ('server', 'port'),
        'MEMORY_SERVER_HOST': ('server', 'host'), 'MEMORY_SESSION_TIMEOUT': ('server', 'session_timeout'),
    }
    for ek, (sec, key) in env_map.items():
        v = os.environ.get(ek)
        if v:
            config[sec][key] = int(v) if key in ('port', 'session_timeout') else v
    return config

_cfg = load_config()
HOST = _cfg['server']['host']
PORT = _cfg['server']['port']
DB_USER = _cfg['database']['user']
DB_PASS = _cfg['database']['password']
DB_DSN = _cfg['database']['dsn']
SESS_TTL = _cfg['server']['session_timeout']

_sessions = {}
_slock = threading.Lock()

def create_session(username):
    tok = hashlib.sha256(os.urandom(32)).hexdigest()[:32]
    with _slock:
        _sessions[tok] = {'username': username, 'created': time_module.time()}
    return tok

def validate_session(tok):
    with _slock:
        if tok not in _sessions:
            return None
        s = _sessions[tok]
        if time_module.time() - s['created'] > SESS_TTL:
            del _sessions[tok]
            return None
        return s['username']

def authenticate(username, password):
    conn = None
    try:
        conn = oracledb.connect(user=DB_USER, password=DB_PASS, dsn=DB_DSN)
        cur = conn.cursor()
        cur.execute("SELECT password_hash, salt, status FROM SYSTEM_USERS WHERE username = :1", [username])
        row = cur.fetchone()
        if not row or row[2] != 'ACTIVE':
            return False
        stored_hash, salt_hex = row[0], row[1]
        salt = bytes.fromhex(salt_hex)
        pw_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
        if pw_hash.hex() == stored_hash:
            cur.execute("UPDATE SYSTEM_USERS SET last_login = SYSTIMESTAMP WHERE username = :1", [username])
            conn.commit()
            return True
        return False
    except Exception as e:
        print(f'Auth error: {e}')
        return False
    finally:
        if conn:
            conn.close()

_pool = None
_plock = threading.Lock()

def get_pool():
    global _pool
    if _pool is None:
        with _plock:
            if _pool is None:
                _pool = oracledb.create_pool(
                    user=DB_USER, password=DB_PASS, dsn=DB_DSN,
                    min=_cfg['database']['pool_min'], max=_cfg['database']['pool_max'],
                    increment=_cfg['database']['pool_increment'],
                    getmode=oracledb.SPOOL_ATTRVAL_NOWAIT)
    return _pool

COLORS = {
    'MEMORY': '#1abc9c', 'KNOWLEDGE': '#e74c3c', 'TASK_OUTPUT': '#9b59b6',
    'EXPERIENCE': '#f39c12', 'FACT': '#3498db', 'RULE': '#2ecc71',
    'PATTERN': '#9b59b6', 'PRINCIPLE': '#e67e22', 'ARCHITECTURE': '#8e44ad',
    'TECHNOLOGY': '#27ae60', 'MEETING': '#16a085', 'SYSTEM': '#e67e22',
    'TESTING': '#d35400', 'GENERAL': '#95a5a6',
}

def ncolor(cat):
    return COLORS.get((cat or '').upper(), '#95a5a6')

_cache = {'knowledge': {'data': None, 'ts': 0}, 'memory': {'data': None, 'ts': 0}}
_clock = threading.Lock()
CACHE_TTL = 300

def load_entity_data(entity_type):
    ck = entity_type.lower()
    with _clock:
        now = time_module.time()
        if _cache[ck]['data'] and now - _cache[ck]['ts'] < CACHE_TTL:
            return _cache[ck]['data']
    pool = get_pool()
    conn = pool.acquire()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT ENTITY_ID, NAME, CATEGORY, VISIBILITY, OWNED_BY_AGENT
                       FROM ENTITIES WHERE ENTITY_TYPE = :t AND STATUS = 'ACTIVE' ORDER BY ENTITY_ID""", {'t': entity_type})
        nodes = []
        for r in cur.fetchall():
            eid, name, cat, vis, owner = r
            name, cat, owner = _fix_encoding(name), _fix_encoding(cat), _fix_encoding(owner)
            nodes.append({'id': str(eid), 'label': (name or '')[:50], 'group': cat or entity_type,
                          'color': ncolor(cat),
                          'title': f"{cat or entity_type}: {name}\nOwner: {owner or 'SYSTEM'} | Vis: {vis}",
                          'visibility': vis or 'SHARED', 'owner': owner or 'SYSTEM'})
        cur.execute("""SELECT SOURCE_ID, TARGET_ID, EDGE_TYPE, STRENGTH, CONFIDENCE
                       FROM ENTITY_EDGES WHERE SOURCE_ID IN (SELECT ENTITY_ID FROM ENTITIES WHERE ENTITY_TYPE=:t)
                          OR TARGET_ID IN (SELECT ENTITY_ID FROM ENTITIES WHERE ENTITY_TYPE=:t) ORDER BY EDGE_ID""", {'t': entity_type})
        edges = []
        for r in cur.fetchall():
            src, tgt, et, st, cf = r
            et = _fix_encoding(et)
            edges.append({'from': str(src), 'to': str(tgt), 'label': str(et) if et else '',
                          'title': f"{et} (strength={st}, confidence={cf})",
                          'arrows': 'to', 'width': max(1, min(5, (st or 1) * 2))})
        data = {'nodes': nodes, 'edges': edges}
        with _clock:
            _cache[ck] = {'data': data, 'ts': now}
        print(f"  Loaded {len(nodes)} {entity_type} nodes, {len(edges)} edges")
        return data
    except Exception as e:
        print(f"  Error loading {entity_type}: {e}")
        return {'nodes': [], 'edges': []}
    finally:
        pool.release(conn)

def load_db_stats():
    pool = get_pool()
    conn = pool.acquire()
    try:
        cur = conn.cursor()
        cur.execute("SELECT ENTITY_TYPE, COUNT(*) FROM ENTITIES WHERE STATUS='ACTIVE' GROUP BY ENTITY_TYPE")
        stats = {_fix_encoding(r[0]): r[1] for r in cur.fetchall()}
        cur.execute("SELECT COUNT(*) FROM ENTITY_EDGES")
        stats['edges'] = cur.fetchone()[0]
        return stats
    except Exception:
        return {}
    finally:
        pool.release(conn)

def _fix_encoding(v):
    if not isinstance(v, str) or not v:
        return v
    has_latin1_range = any(0x80 <= ord(c) <= 0xFF for c in v)
    has_cjk = any(ord(c) >= 0x4E00 for c in v)
    if has_cjk or not has_latin1_range:
        return v
    try:
        raw = bytes([ord(c) for c in v])
        fixed = raw.decode('utf-8')
        return fixed
    except (UnicodeDecodeError, ValueError):
        pass
    try:
        return v.encode('latin-1', errors='replace').decode('utf-8', errors='replace')
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass
    return v

def _sanitize_val(v):
    from decimal import Decimal
    from datetime import datetime, date
    if isinstance(v, Decimal):
        return int(v) if v == int(v) else float(v)
    if isinstance(v, datetime):
        return v.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(v, date):
        return v.strftime('%Y-%m-%d')
    return _fix_encoding(v)

def _q(conn, sql, params=None):
    cur = conn.cursor()
    cur.execute(sql, params or {})
    cols = [c[0].lower() for c in cur.description]
    return [{c: _sanitize_val(v) for c, v in zip(cols, r)} for r in cur.fetchall()]

def load_agents_data():
    pool = get_pool()
    conn = pool.acquire()
    try:
        agents = _q(conn, """SELECT a.AGENT_ID, a.AGENT_NAME, a.AGENT_TYPE, a.DESCRIPTION,
                    a.STATUS, a.PERMISSION_LEVEL, a.CREATED_AT,
                    (SELECT COUNT(*) FROM AGENT_SESSION s WHERE s.AGENT_ID=a.AGENT_ID AND s.IS_ACTIVE='Y') AS active_sessions,
                    (SELECT COUNT(*) FROM ENTITY_ACCESS_LOG l WHERE l.AGENT_ID=a.AGENT_ID) AS access_count
                    FROM AGENT_REGISTRY a ORDER BY a.CREATED_AT""")
        sessions = _q(conn, """SELECT s.SESSION_ID, s.AGENT_ID, a.AGENT_NAME, s.IS_ACTIVE,
                    TO_CHAR(s.START_TIME, 'YYYY-MM-DD HH24:MI:SS') AS START_TIME,
                    TO_CHAR(s.LAST_ACTIVITY, 'YYYY-MM-DD HH24:MI:SS') AS LAST_ACTIVITY
                    FROM AGENT_SESSION s LEFT JOIN AGENT_REGISTRY a ON a.AGENT_ID=s.AGENT_ID
                    ORDER BY s.START_TIME DESC FETCH FIRST 50 ROWS ONLY""")
        collabs = _q(conn, """SELECT c.COLLAB_ID, c.SHARING_AGENT, c.RECEIVING_AGENT,
                    c.SHARE_REASON, c.STATUS,
                    TO_CHAR(c.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
                    sa.AGENT_NAME AS SHARER_NAME, ra.AGENT_NAME AS RECEIVER_NAME
                    FROM AGENT_COLLABORATION c
                    LEFT JOIN AGENT_REGISTRY sa ON sa.AGENT_ID=c.SHARING_AGENT
                    LEFT JOIN AGENT_REGISTRY ra ON ra.AGENT_ID=c.RECEIVING_AGENT
                    ORDER BY c.CREATED_AT DESC FETCH FIRST 50 ROWS ONLY""")
        return {'agents': agents, 'sessions': sessions, 'collaborations': collabs}
    except Exception as e:
        print(f'  Error loading agents: {e}')
        return {'agents': [], 'sessions': [], 'collaborations': []}
    finally:
        pool.release(conn)

def load_tasks_data(status_filter=None, keyword=None):
    pool = get_pool()
    conn = pool.acquire()
    try:
        conds = ['1=1']
        params = {}
        if status_filter and status_filter != 'ALL':
            conds.append("p.STATUS = :st")
            params['st'] = status_filter
        if keyword:
            conds.append("(UPPER(p.PLAN_NAME) LIKE UPPER(:kw) OR UPPER(p.DESCRIPTION) LIKE UPPER(:kw))")
            params['kw'] = f'%{keyword}%'
        where = ' AND '.join(conds)
        plans = _q(conn, f"""SELECT p.PLAN_ID, p.PLAN_NAME, p.PLAN_TYPE, p.STATUS,
                    p.DESCRIPTION, p.GOAL, p.PRIORITY,
                    TO_CHAR(p.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
                    TO_CHAR(p.STARTED_AT, 'YYYY-MM-DD HH24:MI:SS') AS STARTED_AT,
                    TO_CHAR(p.COMPLETED_AT, 'YYYY-MM-DD HH24:MI:SS') AS COMPLETED_AT,
                    (SELECT COUNT(*) FROM TASK_STEPS s WHERE s.PLAN_ID=p.PLAN_ID) AS total_steps,
                    (SELECT COUNT(*) FROM TASK_STEPS s WHERE s.PLAN_ID=p.PLAN_ID AND s.STATUS='SUCCESS') AS done_steps
                    FROM TASK_PLANS p WHERE {where} ORDER BY p.CREATED_AT DESC FETCH FIRST 100 ROWS ONLY""", params)
        plan_ids = [p['plan_id'] for p in plans]
        steps = []
        if plan_ids:
            id_list = ','.join(str(i) for i in plan_ids)
            steps = _q(conn, f"""SELECT s.STEP_ID, s.PLAN_ID, s.STEP_ORDER, s.STEP_NAME,
                        s.ACTION, s.STATUS, s.ERROR_MSG,
                        TO_CHAR(s.STARTED_AT, 'YYYY-MM-DD HH24:MI:SS') AS STARTED_AT,
                        TO_CHAR(s.COMPLETED_AT, 'YYYY-MM-DD HH24:MI:SS') AS COMPLETED_AT
                        FROM TASK_STEPS s WHERE s.PLAN_ID IN ({id_list}) ORDER BY s.PLAN_ID, s.STEP_ORDER""")
        stats = _q(conn, "SELECT STATUS, COUNT(*) AS CNT FROM TASK_PLANS GROUP BY STATUS")
        return {'plans': plans, 'steps': steps, 'stats': {s['status']: s['cnt'] for s in stats}}
    except Exception as e:
        print(f'  Error loading tasks: {e}')
        return {'plans': [], 'steps': [], 'stats': {}}
    finally:
        pool.release(conn)

LOGIN_HTML = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:linear-gradient(135deg,#667eea,#764ba2);min-height:100vh;display:flex;align-items:center;justify-content:center}
.b{background:rgba(255,255,255,.15);backdrop-filter:blur(10px);padding:40px;border-radius:20px;box-shadow:0 20px 60px rgba(0,0,0,.3);width:100%;max-width:400px}
h1{color:#fff;text-align:center;margin-bottom:30px;font-size:24px}
.fg{margin-bottom:20px}label{display:block;color:#fff;margin-bottom:8px;font-weight:700}
input{width:100%;padding:12px;border:none;border-radius:8px;font-size:16px;background:rgba(255,255,255,.9)}
input:focus{outline:2px solid #667eea}
button{width:100%;padding:14px;background:#667eea;color:#fff;border:none;border-radius:8px;font-size:16px;font-weight:700;cursor:pointer}
button:hover{background:#5568d3}.err{color:#ff6b6b;text-align:center;margin-top:15px;font-size:14px}
</style></head><body>
<div class="b"><h1>Oracle Memory System v2.0</h1>
<form id="lf"><div class="fg"><label>Username</label><input name="username" required placeholder="admin"></div>
<div class="fg"><label>Password</label><input type="password" name="password" required></div>
<button type="submit">Login</button></form><div id="err" class="err"></div></div>
<script>
document.getElementById('lf').onsubmit=async e=>{e.preventDefault();const d=document.getElementById('err');
try{const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams(new FormData(e.target))});
if(r.ok)location='/knowledge';else{const j=await r.json();d.textContent=j.error||'Login failed'}}
catch(x){d.textContent='Network error'}};
</script></body></html>"""

def build_page(mode):
    is_kn = mode != 'memory'
    api = '/api/knowledge' if is_kn else '/api/memory'
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Oracle Memory System - {'Knowledge' if is_kn else 'Memory'}</title>
<script src="vis-network.min.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,sans-serif;background:linear-gradient(135deg,#667eea,#764ba2);min-height:100vh}}
.w{{display:flex;height:100vh}}
.s{{width:300px;background:rgba(255,255,255,.1);backdrop-filter:blur(10px);padding:20px;color:#fff;overflow-y:auto;display:flex;flex-direction:column}}
.s h2{{margin-bottom:15px;font-size:20px;border-bottom:2px solid rgba(255,255,255,.3);padding-bottom:10px}}
.s p{{margin-bottom:6px;font-size:13px;line-height:1.5}}
.m{{flex:1;padding:15px}}
#gc{{width:100%;height:100%;background:rgba(255,255,255,.95);border-radius:15px;box-shadow:0 10px 40px rgba(0,0,0,.2)}}
.ld{{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:#fff}}
.sp{{width:50px;height:50px;border:5px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:spin 1s linear infinite}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
.st{{font-weight:700;font-size:14px;margin-top:15px;margin-bottom:8px;border-bottom:1px solid rgba(255,255,255,.2);padding-bottom:5px}}
.nb{{display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap}}
.nb button{{flex:1;padding:8px;background:rgba(255,255,255,.2);color:#fff;border:none;border-radius:5px;cursor:pointer;font-size:13px}}
.nb button:hover{{background:rgba(255,255,255,.35)}}.nb button.a{{background:rgba(255,255,255,.5);font-weight:700}}
.lb{{display:flex;gap:8px}}
.lb button{{flex:1;padding:6px;background:rgba(255,255,255,.2);color:#fff;border:none;border-radius:5px;cursor:pointer;font-size:12px}}
.lb button.a{{background:rgba(255,255,255,.5);font-weight:700}}
.ni{{margin-top:15px;padding:12px;background:rgba(255,255,255,.15);border-radius:8px;display:none}}
.ni.a{{display:block}}.ni h3{{margin-bottom:8px;font-size:14px}}.ni p{{font-size:13px;margin-bottom:4px}}.ni label{{font-weight:700}}
.sb{{margin-top:10px;padding:10px;background:rgba(0,0,0,.2);border-radius:8px;font-size:12px}}
.lo{{margin-top:auto;padding:10px;background:rgba(255,0,0,.3);color:#fff;border:none;border-radius:5px;cursor:pointer;font-size:13px}}
.lo:hover{{background:rgba(255,0,0,.5)}}#tmr{{font-size:11px;color:#ffeb3b;margin-top:5px}}
</style></head><body>
<div class="w"><div class="s">
<h2 id="st"></h2><p><b>Oracle Memory System v2.0</b></p>
<div class="st" id="li"></div><p id="pd"></p><p id="ps"></p><p id="pc"></p>
<div class="st" id="lp"></div>
<div class="nb"><button id="bk" onclick="location='/knowledge'"></button><button id="bm" onclick="location='/memory'"></button><button id="ba" onclick="location='/agents'"></button><button id="bt" onclick="location='/tasks'"></button></div>
<div class="st" id="ll"></div>
<div class="lb"><button id="bz" onclick="setL('zh')">中文</button><button id="be" onclick="setL('en')">EN</button></div>
<div class="ni" id="ni"><h3 id="ld"></h3>
<p><label>ID:</label> <span id="nid">-</span></p>
<p><label id="lt">Type:</label> <span id="nt">-</span></p>
<p><label id="ln">Name:</label> <span id="nl">-</span></p>
<p><label>Owner:</label> <span id="no">-</span></p>
<p><label>Visibility:</label> <span id="nv">-</span></p></div>
<div class="sb" id="sbox"></div><p id="tmr"></p>
<button class="lo" id="blo" onclick="location='/api/logout'"></button>
</div><div class="m">
<div id="ldc" class="ld"><div class="sp"></div><p id="ltxt"></p></div>
<div id="gc" style="display:none"></div>
</div></div>
<script>
const mode='{mode}',api='{api}';
const i18n={{zh:{{t:mode==='memory'?'记忆内容':'知识图谱',i:'操作指南',d:'拖拽：移动节点',s:'滚轮：缩放',c:'点击：查看详情',
k:'知识图谱',m:'记忆内容',a:'Agent',tk:'任务',p:'页面',l:'语言',dt:'节点详情',ty:'类型:',nm:'名称:',lo:'退出登录',ld:'加载中...',st:'统计'}},
en:{{t:mode==='memory'?'Memory Content':'Knowledge Graph',i:'Instructions',d:'Drag: Move nodes',s:'Scroll: Zoom',c:'Click: Details',
k:'Knowledge',m:'Memory',a:'Agents',tk:'Tasks',p:'Pages',l:'Language',dt:'Node Details',ty:'Type:',nm:'Name:',lo:'Logout',ld:'Loading...',st:'Stats'}}}};
function gL(){{return localStorage.getItem('lang')||'zh'}}
function setL(l){{localStorage.setItem('lang',l);aL(l)}}
function aL(l){{const t=i18n[l];document.getElementById('st').textContent=t.t;document.getElementById('li').textContent=t.i;
document.getElementById('pd').textContent=t.d;document.getElementById('ps').textContent=t.s;document.getElementById('pc').textContent=t.c;
document.getElementById('bk').textContent=t.k;document.getElementById('bm').textContent=t.m;document.getElementById('ba').textContent=t.a;document.getElementById('bt').textContent=t.tk;document.getElementById('lp').textContent=t.p;
document.getElementById('ll').textContent=t.l;document.getElementById('ld').textContent=t.dt;
document.getElementById('lt').textContent=t.ty;document.getElementById('ln').textContent=t.nm;
document.getElementById('blo').textContent=t.lo;document.getElementById('ltxt').textContent=t.ld;
document.getElementById('sbox').dataset.label=t.st;
document.getElementById('bz').className='lb button'+(l==='zh'?' a':'');document.getElementById('be').className='lb button'+(l==='en'?' a':'');
document.getElementById('bk').className=mode==='knowledge'?'a':'';document.getElementById('bm').className=mode==='memory'?'a':'';document.getElementById('ba').className='';document.getElementById('bt').className=''}}
aL(gL());
let timer={{s:parseInt('{SESS_TTL}')}};
function startTimer(){{setInterval(()=>{{timer.s--;if(timer.s<=0){{alert(gL()==='zh'?'已超时登出':'Session expired');location='/api/logout'}}
const m=Math.floor(timer.s/60),ss=timer.s%60;document.getElementById('tmr').textContent=(gL()==='zh'?'登出倒计时: ':'Auto-logout: ')+m+'m '+ss+'s'}},1000)}}
['mousedown','keydown','scroll','click','touchstart'].forEach(e=>document.addEventListener(e,()=>{{timer.s=parseInt('{SESS_TTL}')}}));
startTimer();
fetch('/api/stats').then(r=>r.json()).then(s=>{{const box=document.getElementById('sbox');
let h='<b>'+(box.dataset.label||'Stats')+'</b>';for(const[k,v]of Object.entries(s))h+='<br>'+k+': '+v;box.innerHTML=h}}).catch(()=>{{}});
fetch(api).then(r=>r.json()).then(data=>{{const c=document.getElementById('gc'),ld=document.getElementById('ldc');
const nodes=new vis.DataSet(data.nodes),edges=new vis.DataSet(data.edges);
const net=new vis.Network(c,{{nodes,edges}},{{physics:{{enabled:true,stabilization:{{iterations:100}}}},interaction:{{hover:true}},
nodes:{{shape:'dot',font:{{color:'#000',size:12}},borderWidth:2}},edges:{{smooth:true,arrows:{{to:{{enabled:true,scaleFactor:.5}}}}}}}});
ld.style.display='none';c.style.display='block';
net.on('click',p=>{{if(p.nodes.length){{const n=nodes.get(p.nodes[0]);document.getElementById('nid').textContent=n.id;
document.getElementById('nt').textContent=n.group||'-';document.getElementById('nl').textContent=n.label;
document.getElementById('no').textContent=n.owner||'-';document.getElementById('nv').textContent=n.visibility||'-';
document.getElementById('ni').className='ni a'}}}})}}).catch(e=>{{document.getElementById('ldc').innerHTML='<p style="color:#fff">Load failed</p>'}});
</script></body></html>"""

def build_agents_page():
    return f'''<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Oracle Memory System - Agents</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,sans-serif;background:linear-gradient(135deg,#667eea,#764ba2);min-height:100vh}}
.w{{display:flex;height:100vh}}
.s{{width:300px;background:rgba(255,255,255,.1);backdrop-filter:blur(10px);padding:20px;color:#fff;overflow-y:auto;display:flex;flex-direction:column}}
.s h2{{margin-bottom:15px;font-size:20px;border-bottom:2px solid rgba(255,255,255,.3);padding-bottom:10px}}
.s p{{margin-bottom:6px;font-size:13px;line-height:1.5}}
.m{{flex:1;padding:20px;overflow-y:auto}}
.st{{font-weight:700;font-size:14px;margin-top:15px;margin-bottom:8px;border-bottom:1px solid rgba(255,255,255,.2);padding-bottom:5px}}
.nb{{display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap}}
.nb button{{flex:1;padding:8px;background:rgba(255,255,255,.2);color:#fff;border:none;border-radius:5px;cursor:pointer;font-size:13px}}
.nb button:hover{{background:rgba(255,255,255,.35)}}.nb button.a{{background:rgba(255,255,255,.5);font-weight:700}}
.lb{{display:flex;gap:8px}}
.lb button{{flex:1;padding:6px;background:rgba(255,255,255,.2);color:#fff;border:none;border-radius:5px;cursor:pointer;font-size:12px}}
.lb button.a{{background:rgba(255,255,255,.5);font-weight:700}}
.sb{{margin-top:10px;padding:10px;background:rgba(0,0,0,.2);border-radius:8px;font-size:12px}}
.lo{{margin-top:auto;padding:10px;background:rgba(255,0,0,.3);color:#fff;border:none;border-radius:5px;cursor:pointer;font-size:13px}}
.lo:hover{{background:rgba(255,0,0,.5)}}#tmr{{font-size:11px;color:#ffeb3b;margin-top:5px}}
.tbl{{width:100%;border-collapse:collapse;font-size:13px}}
.tbl th{{background:rgba(102,126,234,.2);color:#fff;padding:10px 8px;text-align:left;font-weight:700;border-bottom:2px solid rgba(255,255,255,.2)}}
.tbl td{{padding:8px;border-bottom:1px solid rgba(255,255,255,.1);color:rgba(255,255,255,.9)}}
.tbl tr:hover td{{background:rgba(255,255,255,.05)}}
.badge{{padding:3px 8px;border-radius:4px;font-size:11px;font-weight:700;display:inline-block}}
.bg-green{{background:#27ae60;color:#fff}}.bg-red{{background:#e74c3c;color:#fff}}
.bg-blue{{background:#3498db;color:#fff}}.bg-orange{{background:#f39c12;color:#fff}}
.bg-gray{{background:#95a5a6;color:#fff}}.bg-purple{{background:#8e44ad;color:#fff}}
.bg-yellow{{background:#f1c40f;color:#333}}
.tabs{{display:flex;gap:4px;margin-bottom:20px}}
.tabs button{{padding:10px 20px;background:rgba(255,255,255,.15);color:#fff;border:none;border-radius:8px 8px 0 0;cursor:pointer;font-size:13px}}
.tabs button:hover{{background:rgba(255,255,255,.25)}}.tabs button.a{{background:rgba(255,255,255,.35);font-weight:700}}
.tabc{{display:none}}.tabc.a{{display:block}}
.tw{{overflow-x:auto;background:rgba(255,255,255,.05);border-radius:10px;padding:15px;box-shadow:0 4px 20px rgba(0,0,0,.1)}}
.ld{{display:flex;flex-direction:column;align-items:center;justify-content:center;height:200px;color:#fff}}
.sp{{width:40px;height:40px;border:4px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:spin 1s linear infinite}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
</style></head><body>
<div class="w"><div class="s">
<h2 id="st"></h2><p><b>Oracle Memory System v2.0</b></p>
<div class="st" id="lp"></div>
<div class="nb">
<button id="bk" onclick="location='/knowledge'"></button>
<button id="bm" onclick="location='/memory'"></button>
<button id="ba" class="a" onclick="location='/agents'"></button>
<button id="bt" onclick="location='/tasks'"></button>
</div>
<div class="st" id="ll"></div>
<div class="lb"><button id="bz" onclick="setL('zh')">中文</button><button id="be" onclick="setL('en')">EN</button></div>
<div class="sb" id="sbox"></div><p id="tmr"></p>
<button class="lo" id="blo" onclick="location='/api/logout'"></button>
</div><div class="m">
<div class="tabs">
<button id="t1" class="a" onclick="swTab(0)"></button>
<button id="t2" onclick="swTab(1)"></button>
<button id="t3" onclick="swTab(2)"></button>
</div>
<div id="tc0" class="tabc a"><div class="tw"><div id="agLd" class="ld"><div class="sp"></div><p id="agLdTxt"></p></div><table id="agTbl" class="tbl" style="display:none"><thead><tr><th>ID</th><th id="thN"></th><th id="thT"></th><th id="thS"></th><th id="thP"></th><th id="thAS"></th><th id="thAC"></th><th id="thC"></th></tr></thead><tbody id="agBody"></tbody></table></div></div>
<div id="tc1" class="tabc"><div class="tw"><div id="seLd" class="ld"><div class="sp"></div><p id="seLdTxt"></p></div><table id="seTbl" class="tbl" style="display:none"><thead><tr><th>ID</th><th id="thSN"></th><th id="thSA"></th><th id="thST"></th><th id="thSL"></th></tr></thead><tbody id="seBody"></tbody></table></div></div>
<div id="tc2" class="tabc"><div class="tw"><div id="coLd" class="ld"><div class="sp"></div><p id="coLdTxt"></p></div><table id="coTbl" class="tbl" style="display:none"><thead><tr><th>ID</th><th id="thCF"></th><th id="thCT"></th><th id="thCR"></th><th id="thCS"></th><th id="thCC"></th></tr></thead><tbody id="coBody"></tbody></table></div></div>
</div></div>
<script>
const i18n={{zh:{{t:'多Agent协同',k:'知识图谱',m:'记忆内容',a:'Agent',tk:'任务',p:'页面',l:'语言',lo:'退出登录',ld:'加载中...',st:'统计',t1:'Agent注册表',t2:'活跃会话',t3:'协作请求',thN:'名称',thT:'类型',thS:'状态',thP:'权限',thAS:'活跃会话',thAC:'访问次数',thC:'创建时间',thSN:'Agent名称',thSA:'活跃',thST:'开始时间',thSL:'最近活动',thCF:'发起方',thCT:'接收方',thCR:'原因',thCS:'状态',thCC:'创建时间',noData:'暂无数据'}},en:{{t:'Multi-Agent Collaboration',k:'Knowledge',m:'Memory',a:'Agents',tk:'Tasks',p:'Pages',l:'Language',lo:'Logout',ld:'Loading...',st:'Stats',t1:'Agent Registry',t2:'Active Sessions',t3:'Collaboration Requests',thN:'Name',thT:'Type',thS:'Status',thP:'Permission',thAS:'Active Sessions',thAC:'Access Count',thC:'Created',thSN:'Agent Name',thSA:'Active',thST:'Start Time',thSL:'Last Activity',thCF:'From',thCT:'To',thCR:'Reason',thCS:'Status',thCC:'Created',noData:'No data'}}}};
function gL(){{return localStorage.getItem('lang')||'zh'}}
function setL(l){{localStorage.setItem('lang',l);aL(l)}}
function aL(l){{const t=i18n[l];document.getElementById('st').textContent=t.t;document.getElementById('bk').textContent=t.k;document.getElementById('bm').textContent=t.m;document.getElementById('ba').textContent=t.a;document.getElementById('bt').textContent=t.tk;document.getElementById('lp').textContent=t.p;document.getElementById('ll').textContent=t.l;document.getElementById('blo').textContent=t.lo;document.getElementById('t1').textContent=t.t1;document.getElementById('t2').textContent=t.t2;document.getElementById('t3').textContent=t.t3;document.getElementById('thN').textContent=t.thN;document.getElementById('thT').textContent=t.thT;document.getElementById('thS').textContent=t.thS;document.getElementById('thP').textContent=t.thP;document.getElementById('thAS').textContent=t.thAS;document.getElementById('thAC').textContent=t.thAC;document.getElementById('thC').textContent=t.thC;document.getElementById('thSN').textContent=t.thSN;document.getElementById('thSA').textContent=t.thSA;document.getElementById('thST').textContent=t.thST;document.getElementById('thSL').textContent=t.thSL;document.getElementById('thCF').textContent=t.thCF;document.getElementById('thCT').textContent=t.thCT;document.getElementById('thCR').textContent=t.thCR;document.getElementById('thCS').textContent=t.thCS;document.getElementById('thCC').textContent=t.thCC;document.getElementById('agLdTxt').textContent=t.ld;document.getElementById('seLdTxt').textContent=t.ld;document.getElementById('coLdTxt').textContent=t.ld;document.getElementById('sbox').dataset.label=t.st;document.getElementById('bz').className='lb button'+(l==='zh'?' a':'');document.getElementById('be').className='lb button'+(l==='en'?' a':'');document.getElementById('bk').className='';document.getElementById('bm').className='';document.getElementById('ba').className='a';document.getElementById('bt').className=''}}
aL(gL());
function swTab(i){{document.querySelectorAll('.tabs button').forEach((b,idx)=>b.className=idx===i?'a':'');document.querySelectorAll('.tabc').forEach((c,idx)=>c.className=idx===i?'tabc a':'tabc')}}
let timer={{s:parseInt('{SESS_TTL}')}};
function startTimer(){{setInterval(()=>{{timer.s--;if(timer.s<=0){{alert(gL()==='zh'?'已超时登出':'Session expired');location='/api/logout'}}const m=Math.floor(timer.s/60),ss=timer.s%60;document.getElementById('tmr').textContent=(gL()==='zh'?'登出倒计时: ':'Auto-logout: ')+m+'m '+ss+'s'}},1000)}}
['mousedown','keydown','scroll','click','touchstart'].forEach(e=>document.addEventListener(e,()=>{{timer.s=parseInt('{SESS_TTL}')}}));
startTimer();
fetch('/api/stats').then(r=>r.json()).then(s=>{{const box=document.getElementById('sbox');let h='<b>'+(box.dataset.label||'Stats')+'</b>';for(const[k,v]of Object.entries(s))h+='<br>'+k+': '+v;box.innerHTML=h}}).catch(()=>{{}});
function sBadge(v){{const m={{'ACTIVE':'bg-green','DISABLED':'bg-red','SUSPENDED':'bg-orange'}};return '<span class="badge '+(m[v]||'bg-gray')+'">'+v+'</span>'}}
function pBadge(v){{const m={{'READ_ONLY':'bg-blue','READ_WRITE':'bg-green','ADMIN':'bg-purple'}};return '<span class="badge '+(m[v]||'bg-gray')+'">'+v+'</span>'}}
function aBadge(v){{return '<span class="badge '+(v==='Y'?'bg-green':'bg-gray')+'">'+(v==='Y'?'Y':'N')+'</span>'}}
function cBadge(v){{const m={{'PENDING':'bg-yellow','ACCEPTED':'bg-green','REJECTED':'bg-red','EXPIRED':'bg-gray'}};return '<span class="badge '+(m[v]||'bg-gray')+'">'+v+'</span>'}}
fetch('/api/agents').then(r=>r.json()).then(d=>{{
const t=i18n[gL()];
const agLd=document.getElementById('agLd'),agTbl=document.getElementById('agTbl'),agBody=document.getElementById('agBody');
if(d.agents&&d.agents.length){{agBody.innerHTML=d.agents.map(a=>'<tr><td>'+a.agent_id+'</td><td>'+(a.agent_name||'')+'</td><td>'+(a.agent_type||'')+'</td><td>'+sBadge(a.status||'')+'</td><td>'+pBadge(a.permission_level||'')+'</td><td>'+(a.active_sessions||0)+'</td><td>'+(a.access_count||0)+'</td><td>'+(a.created_at||'-')+'</td></tr>').join('');agLd.style.display='none';agTbl.style.display='table'}}else{{agLd.innerHTML='<p>'+t.noData+'</p>';agLd.querySelector('.sp').style.display='none'}}
const seLd=document.getElementById('seLd'),seTbl=document.getElementById('seTbl'),seBody=document.getElementById('seBody');
if(d.sessions&&d.sessions.length){{seBody.innerHTML=d.sessions.map(s=>'<tr><td title="'+s.session_id+'">'+(s.session_id||'').substring(0,12)+'...</td><td>'+(s.agent_name||'-')+'</td><td>'+aBadge(s.is_active||'N')+'</td><td>'+(s.start_time||'-')+'</td><td>'+(s.last_activity||'-')+'</td></tr>').join('');seLd.style.display='none';seTbl.style.display='table'}}else{{seLd.innerHTML='<p>'+t.noData+'</p>';seLd.querySelector('.sp').style.display='none'}}
const coLd=document.getElementById('coLd'),coTbl=document.getElementById('coTbl'),coBody=document.getElementById('coBody');
if(d.collaborations&&d.collaborations.length){{coBody.innerHTML=d.collaborations.map(c=>'<tr><td>'+c.collab_id+'</td><td>'+(c.sharer_name||c.sharing_agent||'-')+'</td><td>'+(c.receiver_name||c.receiving_agent||'-')+'</td><td>'+(c.share_reason||'-')+'</td><td>'+cBadge(c.status||'')+'</td><td>'+(c.created_at||'-')+'</td></tr>').join('');coLd.style.display='none';coTbl.style.display='table'}}else{{coLd.innerHTML='<p>'+t.noData+'</p>';coLd.querySelector('.sp').style.display='none'}}
}}).catch(e=>{{document.querySelectorAll('.ld').forEach(el=>el.innerHTML='<p style="color:#fff">Load failed</p>')}});
</script></body></html>'''

def build_tasks_page():
    return f'''<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Oracle Memory System - Tasks</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,sans-serif;background:linear-gradient(135deg,#667eea,#764ba2);min-height:100vh}}
.w{{display:flex;height:100vh}}
.s{{width:300px;background:rgba(255,255,255,.1);backdrop-filter:blur(10px);padding:20px;color:#fff;overflow-y:auto;display:flex;flex-direction:column}}
.s h2{{margin-bottom:15px;font-size:20px;border-bottom:2px solid rgba(255,255,255,.3);padding-bottom:10px}}
.s p{{margin-bottom:6px;font-size:13px;line-height:1.5}}
.m{{flex:1;padding:20px;overflow-y:auto}}
.st{{font-weight:700;font-size:14px;margin-top:15px;margin-bottom:8px;border-bottom:1px solid rgba(255,255,255,.2);padding-bottom:5px}}
.nb{{display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap}}
.nb button{{flex:1;padding:8px;background:rgba(255,255,255,.2);color:#fff;border:none;border-radius:5px;cursor:pointer;font-size:13px}}
.nb button:hover{{background:rgba(255,255,255,.35)}}.nb button.a{{background:rgba(255,255,255,.5);font-weight:700}}
.lb{{display:flex;gap:8px}}
.lb button{{flex:1;padding:6px;background:rgba(255,255,255,.2);color:#fff;border:none;border-radius:5px;cursor:pointer;font-size:12px}}
.lb button.a{{background:rgba(255,255,255,.5);font-weight:700}}
.sb{{margin-top:10px;padding:10px;background:rgba(0,0,0,.2);border-radius:8px;font-size:12px}}
.lo{{margin-top:auto;padding:10px;background:rgba(255,0,0,.3);color:#fff;border:none;border-radius:5px;cursor:pointer;font-size:13px}}
.lo:hover{{background:rgba(255,0,0,.5)}}#tmr{{font-size:11px;color:#ffeb3b;margin-top:5px}}
.tbl{{width:100%;border-collapse:collapse;font-size:13px}}
.tbl th{{background:rgba(102,126,234,.2);color:#fff;padding:10px 8px;text-align:left;font-weight:700;border-bottom:2px solid rgba(255,255,255,.2)}}
.tbl td{{padding:8px;border-bottom:1px solid rgba(255,255,255,.1);color:rgba(255,255,255,.9)}}
.tbl tr:hover td{{background:rgba(255,255,255,.05)}}
.badge{{padding:3px 8px;border-radius:4px;font-size:11px;font-weight:700;display:inline-block}}
.bg-green{{background:#27ae60;color:#fff}}.bg-red{{background:#e74c3c;color:#fff}}
.bg-blue{{background:#3498db;color:#fff}}.bg-orange{{background:#f39c12;color:#fff}}
.bg-gray{{background:#95a5a6;color:#fff}}.bg-purple{{background:#8e44ad;color:#fff}}
.bg-yellow{{background:#f1c40f;color:#333}}
.topbar{{display:flex;gap:10px;margin-bottom:20px;align-items:center;flex-wrap:wrap}}
.topbar select,.topbar input{{padding:8px 12px;border:none;border-radius:5px;font-size:13px;background:rgba(255,255,255,.9);color:#333}}
.topbar input{{flex:1;min-width:150px}}
.topbar button{{padding:8px 16px;background:#667eea;color:#fff;border:none;border-radius:5px;cursor:pointer;font-size:13px}}
.topbar button:hover{{background:#5568d3}}
.sbadge{{font-size:12px;padding:2px 8px;border-radius:3px;display:inline-block;margin-left:6px}}
.plan{{background:rgba(255,255,255,.08);border-radius:10px;margin-bottom:12px;overflow:hidden}}
.plan-h{{padding:14px 16px;cursor:pointer;display:flex;align-items:center;gap:12px;flex-wrap:wrap}}
.plan-h:hover{{background:rgba(255,255,255,.05)}}
.plan-h .pn{{font-size:15px;font-weight:700;color:#fff;flex:1}}
.plan-b{{display:none;padding:0 16px 14px}}
.plan-b.a{{display:block}}
.pbar{{height:6px;background:rgba(255,255,255,.2);border-radius:3px;width:80px;display:inline-block;vertical-align:middle}}
.pbar-f{{height:100%;background:#27ae60;border-radius:3px}}
.ld{{display:flex;flex-direction:column;align-items:center;justify-content:center;height:200px;color:#fff}}
.sp{{width:40px;height:40px;border:4px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:spin 1s linear infinite}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
</style></head><body>
<div class="w"><div class="s">
<h2 id="st"></h2><p><b>Oracle Memory System v2.0</b></p>
<div class="st" id="lp"></div>
<div class="nb">
<button id="bk" onclick="location='/knowledge'"></button>
<button id="bm" onclick="location='/memory'"></button>
<button id="ba" onclick="location='/agents'"></button>
<button id="bt" class="a" onclick="location='/tasks'"></button>
</div>
<div class="st" id="ll"></div>
<div class="lb"><button id="bz" onclick="setL('zh')">中文</button><button id="be" onclick="setL('en')">EN</button></div>
<div class="sb" id="sbox"></div><p id="tmr"></p>
<button class="lo" id="blo" onclick="location='/api/logout'"></button>
</div><div class="m">
<div class="topbar">
<select id="sf" onchange="loadTasks()">
<option value="ALL">ALL</option><option value="PENDING">PENDING</option><option value="RUNNING">RUNNING</option><option value="SUCCESS">SUCCESS</option><option value="FAILED">FAILED</option><option value="CANCELLED">CANCELLED</option><option value="BLOCKED">BLOCKED</option>
</select>
<input id="kw" placeholder="Search..." onkeydown="if(event.key==='Enter')loadTasks()">
<button id="sbtn" onclick="loadTasks()"></button>
<span id="sstats"></span>
</div>
<div id="plc"><div id="pld" class="ld"><div class="sp"></div><p id="pldTxt"></p></div></div>
</div></div>
<script>
const i18n={{zh:{{t:'任务计划',k:'知识图谱',m:'记忆内容',a:'Agent',tk:'任务',p:'页面',l:'语言',lo:'退出登录',ld:'加载中...',st:'统计',search:'搜索',planName:'计划名称',type:'类型',priority:'优先级',progress:'进度',created:'创建',completed:'完成',order:'序号',stepName:'步骤名称',action:'动作',started:'开始',error:'错误',noData:'暂无数据',total:'总计',done:'完成',failed:'失败',running:'运行中',thS:'状态'}},en:{{t:'Task Plans',k:'Knowledge',m:'Memory',a:'Agents',tk:'Tasks',p:'Pages',l:'Language',lo:'Logout',ld:'Loading...',st:'Stats',search:'Search',planName:'Plan Name',type:'Type',priority:'Priority',progress:'Progress',created:'Created',completed:'Completed',order:'Order',stepName:'Step Name',action:'Action',started:'Started',error:'Error',noData:'No data',total:'Total',done:'Done',failed:'Failed',running:'Running',thS:'Status'}}}};
function gL(){{return localStorage.getItem('lang')||'zh'}}
function setL(l){{localStorage.setItem('lang',l);aL(l)}}
function aL(l){{const t=i18n[l];document.getElementById('st').textContent=t.t;document.getElementById('bk').textContent=t.k;document.getElementById('bm').textContent=t.m;document.getElementById('ba').textContent=t.a;document.getElementById('bt').textContent=t.tk;document.getElementById('lp').textContent=t.p;document.getElementById('ll').textContent=t.l;document.getElementById('blo').textContent=t.lo;document.getElementById('sbtn').textContent=t.search;document.getElementById('kw').placeholder=t.search+'...';document.getElementById('sbox').dataset.label=t.st;document.getElementById('bz').className='lb button'+(l==='zh'?' a':'');document.getElementById('be').className='lb button'+(l==='en'?' a':'');document.getElementById('bk').className='';document.getElementById('bm').className='';document.getElementById('ba').className='';document.getElementById('bt').className='a'}}
aL(gL());
let timer={{s:parseInt('{SESS_TTL}')}};
function startTimer(){{setInterval(()=>{{timer.s--;if(timer.s<=0){{alert(gL()==='zh'?'已超时登出':'Session expired');location='/api/logout'}}const m=Math.floor(timer.s/60),ss=timer.s%60;document.getElementById('tmr').textContent=(gL()==='zh'?'登出倒计时: ':'Auto-logout: ')+m+'m '+ss+'s'}},1000)}}
['mousedown','keydown','scroll','click','touchstart'].forEach(e=>document.addEventListener(e,()=>{{timer.s=parseInt('{SESS_TTL}')}}));
startTimer();
fetch('/api/stats').then(r=>r.json()).then(s=>{{const box=document.getElementById('sbox');let h='<b>'+(box.dataset.label||'Stats')+'</b>';for(const[k,v]of Object.entries(s))h+='<br>'+k+': '+v;box.innerHTML=h}}).catch(()=>{{}});
function psBadge(v){{const m={{'PENDING':'bg-gray','RUNNING':'bg-blue','SUCCESS':'bg-green','FAILED':'bg-red','CANCELLED':'bg-orange','BLOCKED':'bg-yellow'}};return '<span class="badge '+(m[v]||'bg-gray')+'">'+v+'</span>'}}
function ssBadge(v){{const m={{'PENDING':'bg-gray','RUNNING':'bg-blue','SUCCESS':'bg-green','FAILED':'bg-red','CANCELLED':'bg-orange','BLOCKED':'bg-yellow'}};return '<span class="badge '+(m[v]||'bg-gray')+'">'+v+'</span>'}}
function loadTasks(){{
const st=document.getElementById('sf').value,kw=document.getElementById('kw').value;
const plc=document.getElementById('plc');
plc.innerHTML='<div class="ld"><div class="sp"></div><p>'+i18n[gL()].ld+'</p></div>';
let url='/api/tasks?status='+st;if(kw)url+='&keyword='+encodeURIComponent(kw);
fetch(url).then(r=>r.json()).then(d=>{{
const t=i18n[gL()],ss=d.stats||{{}};
document.getElementById('sstats').innerHTML='<span class="sbadge bg-gray">'+t.total+': '+(d.plans?d.plans.length:0)+'</span><span class="sbadge bg-green">'+t.done+': '+(ss.SUCCESS||0)+'</span><span class="sbadge bg-red">'+t.failed+': '+(ss.FAILED||0)+'</span><span class="sbadge bg-blue">'+t.running+': '+(ss.RUNNING||0)+'</span>';
if(!d.plans||!d.plans.length){{plc.innerHTML='<div class="ld"><p>'+t.noData+'</p></div>';return}}
let h='';d.plans.forEach(p=>{{
const steps=d.steps.filter(s=>s.plan_id===p.plan_id);
h+='<div class="plan"><div class="plan-h" onclick="this.nextElementSibling.classList.toggle(\\'a\\')"><span class="pn">'+p.plan_name+'</span>'+psBadge(p.status)+'<span style="color:rgba(255,255,255,.7);font-size:12px">'+(p.plan_type||'')+'</span><span style="color:rgba(255,255,255,.7);font-size:12px">P'+(p.priority||0)+'</span><span style="color:rgba(255,255,255,.7);font-size:12px"><span class="pbar"><span class="pbar-f" style="width:'+((p.total_steps?Math.round(p.done_steps/p.total_steps*100):0))+'%"></span></span> '+(p.done_steps||0)+'/'+(p.total_steps||0)+'</span><span style="color:rgba(255,255,255,.5);font-size:11px">'+(p.created_at||'')+'</span></div>';
h+='<div class="plan-b">';if(steps.length){{h+='<table class="tbl"><thead><tr><th>'+t.order+'</th><th>'+t.stepName+'</th><th>'+t.action+'</th><th>'+t.thS+'</th><th>'+t.started+'</th><th>'+t.completed+'</th><th>'+t.error+'</th></tr></thead><tbody>';steps.forEach(s=>{{h+='<tr><td>'+s.step_order+'</td><td>'+s.step_name+'</td><td>'+(s.action||'-')+'</td><td>'+ssBadge(s.status)+'</td><td>'+(s.started_at||'-')+'</td><td>'+(s.completed_at||'-')+'</td><td style="color:#e74c3c">'+(s.error_msg||'-')+'</td></tr>'}});h+='</tbody></table>'}}h+='</div></div>'}});
plc.innerHTML=h
}}).catch(e=>{{plc.innerHTML='<div class="ld"><p style="color:#fff">Load failed</p></div>'}});
}}
loadTasks();
</script></body></html>'''

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def _check_auth(self):
        ck = self.headers.get('Cookie', '')
        for c in ck.split(';'):
            c = c.strip()
            if c.startswith('session='):
                tok = c[8:]
                if validate_session(tok):
                    return True
        return False

    def _redirect(self, path):
        self.send_response(302); self.send_header('Location', path); self.end_headers()

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self._cors(); self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode('utf-8'))

    def _send_html(self, html):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self._cors(); self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def do_GET(self):
        try:
            self._do_GET()
        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                self.send_response(500)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(f'Error: {e}'.encode('utf-8'))
            except:
                pass

    def _do_GET(self):
        path = urlparse(self.path).path
        if path == '/login':
            self._send_html(LOGIN_HTML); return
        if path == '/api/health':
            self._send_json({'status': 'ok', 'pool': _pool is not None}); return
        if path == '/vis-network.min.js':
            fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vis-network.min.js')
            if os.path.isfile(fp):
                self.send_response(200)
                self.send_header('Content-Type', 'application/javascript; charset=utf-8')
                self.send_header('Cache-Control', 'public, max-age=3600')
                self.end_headers()
                with open(fp, 'rb') as f:
                    self.wfile.write(f.read())
                return
        if not self._check_auth():
            self._redirect('/login'); return
        if path in ('/', '/index.html'):
            self._redirect('/knowledge')
        elif path == '/knowledge':
            self._send_html(build_page('knowledge'))
        elif path == '/memory':
            self._send_html(build_page('memory'))
        elif path == '/api/knowledge':
            self._send_json(load_entity_data('KNOWLEDGE'))
        elif path == '/api/knowledge/refresh':
            with _clock:
                _cache['knowledge'] = {'data': None, 'ts': 0}
            self._send_json(load_entity_data('KNOWLEDGE'))
        elif path == '/api/memory':
            self._send_json(load_entity_data('MEMORY'))
        elif path == '/api/memory/refresh':
            with _clock:
                _cache['memory'] = {'data': None, 'ts': 0}
            self._send_json(load_entity_data('MEMORY'))
        elif path == '/agents':
            self._send_html(build_agents_page())
        elif path == '/tasks':
            self._send_html(build_tasks_page())
        elif path == '/api/agents':
            self._send_json(load_agents_data())
        elif path == '/api/tasks':
            qs = parse_qs(urlparse(self.path).query)
            st = qs.get('status', ['ALL'])[0]
            kw = qs.get('keyword', [None])[0]
            self._send_json(load_tasks_data(st if st != 'ALL' else None, kw))
        elif path == '/api/stats':
            self._send_json(load_db_stats())
        elif path == '/api/logout':
            self.send_response(302)
            self.send_header('Set-Cookie', 'session=; Path=/; Max-Age=0')
            self.send_header('Location', '/login'); self.end_headers()
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == '/api/login':
            cl = int(self.headers.get('Content-Length', 0))
            pd = self.rfile.read(cl).decode('utf-8')
            params = {}
            for p in pd.split('&'):
                if '=' in p:
                    k, v = p.split('=', 1)
                    params[k] = v
            if authenticate(params.get('username', ''), params.get('password', '')):
                tok = create_session(params['username'])
                self.send_response(302)
                self.send_header('Set-Cookie', f'session={tok}; Path=/; HttpOnly; SameSite=Strict')
                self.send_header('Location', '/knowledge'); self.end_headers()
            else:
                self._send_json({'error': 'Invalid credentials'}, 401)
        else:
            self.send_response(404); self.end_headers()

def main():
    print("\n" + "=" * 60)
    print("  Oracle Memory System - Web Visualization Server v2.0.0")
    print("=" * 60)
    try:
        get_pool()
        load_entity_data('KNOWLEDGE')
        load_entity_data('MEMORY')
    except Exception as e:
        print(f"  Data preload warning: {e}")
    print(f"\n  Server: http://{HOST}:{PORT}")
    print(f"  Login:  admin / admin123")
    print(f"  Timeout: {SESS_TTL}s")
    print("=" * 60)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer((HOST, PORT), Handler) as srv:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped")
            if _pool:
                _pool.close()
        except Exception as e:
            print(f"\nServer error: {e}")
            import traceback; traceback.print_exc()
            if _pool:
                _pool.close()

if __name__ == '__main__':
    main()
