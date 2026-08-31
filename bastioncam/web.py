from __future__ import annotations

import html
import hashlib
import hmac
import json
import calendar
from datetime import datetime, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse
from zoneinfo import ZoneInfo

from .auth import TokenError, authenticate, create_collector
from .db import connect, cosine, decode_embedding
from .llm import embed_query
from .search import fts_expression, parse_query
from .security import redact_text
from .webauth import check_credentials, create_session, create_user, delete_session, session_user

CSS = """
body{margin:0;background:#11151b;color:#d8dee9;font:15px system-ui}main{max-width:1450px;margin:auto;padding:28px}.layout{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:28px}.primary{min-width:0}aside{border-left:1px solid #303846;padding-left:22px;position:sticky;top:20px;align-self:start;max-height:calc(100vh - 40px);overflow:auto}aside h2{font-size:16px;margin:8px 0}.period-card{background:#181e27;border:1px solid #303846;border-radius:8px;padding:11px;margin:9px 0}.period-card p{white-space:pre-wrap;font-size:13px;line-height:1.35;margin:6px 0}.period-title{color:#9db4d8;font-size:12px}
h1{font-size:22px}form,.controls,.actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}input[type=search]{flex:1;min-width:260px;padding:12px}input,select{background:#202630;color:#fff;border:1px solid #455066;border-radius:7px;padding:8px}button,a.btn{padding:10px 14px;background:#5277c3;color:white;border:0;border-radius:7px;text-decoration:none;cursor:pointer}
.result{padding:16px 0;border-bottom:1px solid #303846}.meta{color:#8fa1bd;font-size:13px}.summary{color:#c8d3e6;line-height:1.45}.badge{display:inline-block;padding:2px 7px;border-radius:10px;background:#29354a;color:#b9cff5}.episode{margin:7px 0;color:#9eacc2;font-size:13px}
pre{white-space:pre-wrap;background:#080b0f;padding:18px;border-radius:8px;min-height:360px;overflow:auto;line-height:1.35}.added{display:block;background:#163522;border-left:3px solid #4fb477;padding-left:5px}.controls{margin:12px 0}.controls input[type=range]{flex:1;min-width:220px}.clock{font-variant-numeric:tabular-nums}.muted{color:#8290a8}
.calendar-head{display:flex;justify-content:space-between;align-items:center;margin:18px 0}.calendar{display:grid;grid-template-columns:repeat(7,minmax(60px,1fr));gap:5px}.weekday{text-align:center;color:#8290a8;padding:7px}.day{min-height:72px;background:#181e27;border:1px solid #303846;border-radius:7px;padding:8px;color:#d8dee9;text-decoration:none}.day.outside{opacity:.25}.day.active{border-color:#5277c3;background:#1d2940}.day.selected{outline:2px solid #78a4ff}.day-count{display:block;color:#8fa1bd;font-size:11px;margin-top:18px}.day-summary,.hour-summary{background:#181e27;border:1px solid #303846;border-radius:8px;padding:14px;margin:10px 0}.day-summary p,.hour-summary p{white-space:pre-wrap}.hour-summary h3{margin:0 0 7px;font-size:15px;color:#9db4d8}
.episode-link{color:#9db4d8;text-decoration:underline;text-underline-offset:3px}.episode-link:hover{color:#fff}
.token{width:100%;min-height:110px;box-sizing:border-box;background:#080b0f;color:#d8dee9;border:1px solid #455066;border-radius:7px;padding:10px;overflow-wrap:anywhere}.collector-row{display:grid;grid-template-columns:minmax(180px,1fr) 2fr;gap:12px;padding:12px 0;border-bottom:1px solid #303846}.notice{padding:12px;border:1px solid #5277c3;background:#1d2940;border-radius:7px;margin:14px 0}
@media(max-width:900px){.layout{grid-template-columns:1fr}aside{position:static;border-left:0;border-top:1px solid #303846;padding:18px 0 0;max-height:none}}
"""

PLAYER_JS = """
<script>
const initialId=INITIAL_ID; let timeline=[],index=0,timer=null,previous='';
const screenEl=document.getElementById('screen'), sliderEl=document.getElementById('slider');
const esc=s=>s.replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));
const fail=e=>{screenEl.textContent='Player error: '+(e?.message||e);console.error(e)};
async function loadFrame(i,highlight=true){
  if(i<0||i>=timeline.length)return; const old=screenEl.textContent;
  const r=await fetch('/api/snapshot/'+timeline[i].id);if(!r.ok)throw new Error('snapshot API '+r.status);const d=await r.json();index=i;sliderEl.value=i;
  document.getElementById('clock').textContent=new Date(d.captured_at).toLocaleString();
  document.getElementById('position').textContent=(i+1)+' / '+timeline.length;
  document.getElementById('jump').value=d.captured_at.slice(0,16);
  const oldLines=new Set(old.split('\\n'));
  screenEl.innerHTML=d.content.split('\\n').map(l=>highlight&&old&&l.trim()&&!oldLines.has(l)?'<span class=added>'+esc(l)+'</span>':esc(l)).join('\\n');
  history.replaceState(null,'','/snapshot/'+d.id); previous=d.content;
}
function stop(){if(timer)clearTimeout(timer);timer=null;document.getElementById('play').textContent='▶';}
function play(){if(timer){stop();return}document.getElementById('play').textContent='⏸';step();}
function step(){if(index>=timeline.length-1){stop();return}const speed=+document.getElementById('speed').value;
  const gap=Math.max(100,Math.min(3000,(new Date(timeline[index+1].captured_at)-new Date(timeline[index].captured_at))/speed));
  timer=setTimeout(async()=>{await loadFrame(index+1);step()},gap)}
sliderEl.oninput=()=>{stop();loadFrame(+sliderEl.value).catch(fail)};
document.getElementById('prev').onclick=()=>{stop();loadFrame(index-1).catch(fail)};
document.getElementById('next').onclick=()=>{stop();loadFrame(index+1).catch(fail)};
document.getElementById('play').onclick=play;
document.getElementById('jump').onchange=e=>{const t=new Date(e.target.value);let best=0,dist=Infinity;timeline.forEach((x,i)=>{const d=Math.abs(new Date(x.captured_at)-t);if(d<dist){dist=d;best=i}});stop();loadFrame(best)};
fetch('/api/timeline/'+initialId).then(r=>{if(!r.ok)throw new Error('timeline API '+r.status);return r.json()}).then(d=>{timeline=d.snapshots;index=Math.max(0,timeline.findIndex(x=>x.id===initialId));sliderEl.max=Math.max(0,timeline.length-1);return loadFrame(index,false)}).catch(fail);
</script>
"""


def page(body: str, sidebar: str, title: str = "BastionCam") -> bytes:
    return f"<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width'><title>{title}</title><style>{CSS}</style></head><body><main><div class=layout><section class=primary>{body}</section><aside>{sidebar}</aside></div></main></body></html>".encode()


class App(BaseHTTPRequestHandler):
    db_path = "history.db"
    ollama_url = "http://127.0.0.1:11434"
    embed_model = "nomic-embed-text"

    def cookie_token(self) -> str:
        cookie=SimpleCookie();cookie.load(self.headers.get("Cookie", ""))
        return cookie["zh_session"].value if "zh_session" in cookie else ""

    def current_user(self) -> dict | None:
        db=connect(self.db_path)
        try:return session_user(db,self.cookie_token())
        finally:db.close()

    def users_exist(self) -> bool:
        db=connect(self.db_path)
        try:return bool(db.execute("SELECT 1 FROM users LIMIT 1").fetchone())
        finally:db.close()

    def redirect(self, location: str, cookie: str = "") -> None:
        self.send_response(303);self.send_header("Location",location)
        if cookie:self.send_header("Set-Cookie",cookie)
        self.send_header("Content-Length","0");self.end_headers()

    def send_auth_page(self, body: str, status: int = 200) -> None:
        data=page(body,"",title="BastionCam login");self.send_response(status)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data)

    def require_user(self) -> dict | None:
        user=self.current_user()
        if not user:self.redirect("/setup" if not self.users_exist() else "/login")
        return user

    def form_values(self, maximum: int = 8192) -> dict[str,list[str]]:
        length=int(self.headers.get("Content-Length","0"))
        if length <= 0 or length > maximum:raise ValueError("invalid form size")
        return parse_qs(self.rfile.read(length).decode())

    @staticmethod
    def valid_csrf(user: dict, values: dict[str,list[str]]) -> bool:
        return hmac.compare_digest(user["csrf_token"],values.get("csrf",[""])[0])

    def send_page(self, body: str, status: int = 200) -> None:
        data = page(body, self.sidebar()); self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(data)))
        self.end_headers(); self.wfile.write(data)

    def sidebar(self) -> str:
        user=self.current_user();csrf=html.escape(user["csrf_token"] if user else "")
        db = connect(self.db_path)
        rows = db.execute("""SELECT period_type,period_start,period_end,summary,segment_count
            FROM period_summaries ORDER BY period_start DESC,period_type LIMIT 12""").fetchall(); db.close()
        if not rows:
            return f"<h2>Summaries</h2><p class=muted>Summaries will appear after the first episodes are processed.</p><p><a href='/admin/collectors'>Collector admin</a> · <a href='/admin/users'>Users</a></p><form method=post action='/logout'><input type=hidden name=csrf value='{csrf}'><button>Log out</button></form>"
        tz = ZoneInfo("Europe/Prague"); cards=[]
        for row in rows:
            start=datetime.fromisoformat(row["period_start"]).astimezone(tz)
            label=start.strftime("%d.%m.%Y, %H:00") if row["period_type"]=="hour" else start.strftime("%d.%m.%Y")
            kind="Hour" if row["period_type"]=="hour" else "Day"
            cards.append(f"<a href='/?month={start:%Y-%m}&day={start:%Y-%m-%d}' style='color:inherit;text-decoration:none'><div class=period-card><div class=period-title>{kind} · {label} · episodes: {row['segment_count']}</div><p>{html.escape(row['summary'])}</p></div></a>")
        return "<h2><a href='/' style='color:inherit'>Work summaries</a></h2>"+"".join(cards)+f"<p><a href='/admin/collectors'>Collector admin</a> · <a href='/admin/users'>Users</a></p><form method=post action='/logout'><input type=hidden name=csrf value='{csrf}'><button>Log out</button></form>"

    def send_json(self, value: object, status: int = 200) -> None:
        data = json.dumps(value, ensure_ascii=False).encode(); self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_GET(self) -> None:
        url = urlparse(self.path)
        try:
            if url.path == "/healthz": return self.send_json({"status": "ok"})
            if url.path == "/setup":return self.setup_page()
            if url.path == "/login":return self.login_page()
            if not self.require_user():return
            if url.path == "/":
                params=parse_qs(url.query)
                query=params.get("q",[""])[0]
                if query.strip() or "start" in params or "end" in params:
                    return self.index(query,params.get("start",[""])[0],params.get("end",[""])[0])
                return self.calendar_view(params.get("month",[""])[0],params.get("day",[""])[0])
            if url.path == "/calendar":
                params=parse_qs(url.query); return self.calendar_view(params.get("month",[""])[0],params.get("day",[""])[0])
            if url.path == "/admin/collectors": return self.admin_collectors()
            if url.path == "/admin/users": return self.admin_users()
            if url.path.startswith("/snapshot/"): return self.player(int(url.path.rsplit("/", 1)[1]))
            if url.path.startswith("/api/snapshot/"): return self.api_snapshot(int(url.path.rsplit("/", 1)[1]))
            if url.path.startswith("/api/timeline/"): return self.api_timeline(int(url.path.rsplit("/", 1)[1]))
        except ValueError:
            pass
        self.send_error(404)

    def calendar_view(self, month_value: str, day_value: str) -> None:
        tz=ZoneInfo("Europe/Prague"); today=datetime.now(tz).date()
        try: month=datetime.strptime(month_value,"%Y-%m").date().replace(day=1) if month_value else today.replace(day=1)
        except ValueError: month=today.replace(day=1)
        try: selected=datetime.strptime(day_value,"%Y-%m-%d").date() if day_value else (today if month==today.replace(day=1) else month)
        except ValueError: selected=today
        db=connect(self.db_path)
        snapshot_rows=db.execute("SELECT captured_at FROM snapshots ORDER BY captured_at").fetchall()
        summary_rows=db.execute("SELECT period_type,period_start,period_end,summary,segment_count FROM period_summaries ORDER BY period_start").fetchall();db.close()
        activity:dict[str,int]={}
        for row in snapshot_rows:
            key=datetime.fromisoformat(row["captured_at"]).astimezone(tz).date().isoformat();activity[key]=activity.get(key,0)+1
        summaries=[]
        for row in summary_rows:
            item=dict(row);local=datetime.fromisoformat(row["period_start"]).astimezone(tz);item["local"]=local
            if local.date()==selected:summaries.append(item)
        previous=(month.replace(day=1)-timedelta(days=1)).replace(day=1)
        next_month=(month.replace(day=28)+timedelta(days=4)).replace(day=1)
        header=f"<div class=calendar-head><a class=btn href='/?month={previous:%Y-%m}'>&larr;</a><h1>{month.strftime('%B %Y')}</h1><a class=btn href='/?month={next_month:%Y-%m}'>&rarr;</a></div>"
        weekdays="".join(f"<div class=weekday>{name}</div>" for name in calendar.day_abbr)
        cells=[]
        for date in calendar.Calendar(firstweekday=0).itermonthdates(month.year,month.month):
            key=date.isoformat();classes=["day"]
            if date.month!=month.month:classes.append("outside")
            if key in activity:classes.append("active")
            if date==selected:classes.append("selected")
            count=f"<span class=day-count>{activity[key]} snapshots</span>" if key in activity else ""
            cells.append(f"<a class='{' '.join(classes)}' href='/?month={month:%Y-%m}&day={key}'><strong>{date.day}</strong>{count}</a>")
        daily=next((s for s in summaries if s["period_type"]=="day"),None)
        hours=sorted((s for s in summaries if s["period_type"]=="hour"),key=lambda s:s["local"])
        detail=f"<h2>{selected.strftime('%A, %d %B %Y')}</h2>"
        if daily:
            query=urlencode({"start":daily["period_start"],"end":daily["period_end"]})
            count=daily["segment_count"]
            label=f"{count} episode{'s' if count != 1 else ''}"
            detail+=f"<div class=day-summary><h3>Daily summary</h3><p>{html.escape(daily['summary'])}</p><div class=meta><a class=episode-link href='/?{query}'>{label}</a></div></div>"
        elif selected.isoformat() in activity:detail+="<div class=day-summary><h3>Daily summary</h3><p class=muted>Summary is pending.</p></div>"
        else:detail+="<p class=muted>No recorded activity.</p>"
        if hours:
            hour_cards=[]
            for summary in hours:
                query=urlencode({"start":summary["period_start"],"end":summary["period_end"]})
                count=summary["segment_count"]
                label=f"{count} episode{'s' if count != 1 else ''}"
                hour_cards.append(f"<div class=hour-summary><h3>{summary['local']:%H:00}</h3><p>{html.escape(summary['summary'])}</p><div class=meta><a class=episode-link href='/?{query}'>{label}</a></div></div>")
            detail+="<h2>Hour by hour</h2>"+"".join(hour_cards)
        elif selected.isoformat() in activity:detail+="<h2>Hour by hour</h2><p class=muted>Hourly summaries are pending.</p>"
        self.send_page(self.search_form()+header+f"<div class=calendar>{weekdays}{''.join(cells)}</div>"+detail)

    def do_POST(self) -> None:
        path=urlparse(self.path).path
        if path == "/setup":return self.setup_submit()
        if path == "/login":return self.login_submit()
        if path != "/api/ingest":
            user=self.require_user()
            if not user:return
            try:values=self.form_values()
            except (ValueError,UnicodeDecodeError):return self.send_error(400)
            if not self.valid_csrf(user,values):return self.send_error(403,"Invalid CSRF token")
            if path == "/logout":
                db=connect(self.db_path)
                try:delete_session(db,self.cookie_token())
                finally:db.close()
                return self.redirect("/login","zh_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")
            if path == "/admin/users":
                try:
                    password=values.get("password",[""])[0]
                    if password != values.get("confirm_password",[""])[0]:raise ValueError("passwords do not match")
                    db=connect(self.db_path)
                    try:new_user=create_user(db,values.get("username",[""])[0],password)
                    finally:db.close()
                    return self.admin_users(message=f"Created user {new_user['username']}.")
                except ValueError as error:return self.admin_users(error=str(error),status=400)
                except Exception as error:
                    message="That username already exists." if "UNIQUE constraint failed" in str(error) else "Could not create user."
                    return self.admin_users(error=message,status=409)
            if path == "/admin/collectors":
                try:
                    db=connect(self.db_path)
                    try:collector,token=create_collector(db,values.get("name",[""])[0])
                    finally:db.close()
                    return self.admin_collectors(token=token,created_name=collector["name"])
                except ValueError as error:return self.admin_collectors(error=str(error),status=400)
                except Exception as error:
                    message="A collector with that name already exists." if "UNIQUE constraint failed" in str(error) else "Could not create collector."
                    return self.admin_collectors(error=message,status=409)
            return self.send_error(404)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 2 * 1024 * 1024:
                return self.send_json({"error": "invalid payload size"}, 413)
            payload = json.loads(self.rfile.read(length))
            required = ("session_name", "pane_key", "captured_at", "content")
            if any(not isinstance(payload.get(key), str) or not payload[key] for key in required):
                return self.send_json({"error": "missing required fields"}, 400)
            datetime.fromisoformat(payload["captured_at"].replace("Z", "+00:00"))
            content = redact_text(payload["content"])
            stamp = datetime.now(ZoneInfo("UTC")).isoformat(timespec="seconds")
            db = connect(self.db_path)
            try:
                collector=authenticate(db,self.headers.get("Authorization"))
            except TokenError as error:
                db.close();return self.send_json({"error":str(error)},401)
            session = f"{collector['name'][:120]}/{payload['session_name'][:160]}"
            db.execute("""INSERT INTO panes(collector_id,session_name,pane_key,tab_name,title,command,cwd,first_seen,last_seen)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(session_name,pane_key) DO UPDATE SET
                collector_id=excluded.collector_id,
                tab_name=excluded.tab_name,title=excluded.title,command=excluded.command,
                cwd=excluded.cwd,last_seen=excluded.last_seen""",
                (collector["id"],session,payload["pane_key"][:100],payload.get("tab_name", "")[:300],
                 redact_text(payload.get("title", ""))[:500], redact_text(payload.get("command", ""))[:1000],
                 redact_text(payload.get("cwd", ""))[:2000], stamp, stamp))
            pane_id = db.execute("SELECT id FROM panes WHERE session_name=? AND pane_key=?",
                                 (session, payload["pane_key"][:100])).fetchone()[0]
            digest = hashlib.sha256(content.encode()).hexdigest()
            previous = db.execute("SELECT content_hash FROM snapshots WHERE pane_id=? ORDER BY id DESC LIMIT 1",
                                  (pane_id,)).fetchone()
            created = not previous or previous[0] != digest
            if created:
                db.execute("INSERT INTO snapshots(pane_id,captured_at,content,content_hash,delivered_at) VALUES(?,?,?,?,?)",
                           (pane_id, payload["captured_at"], content, digest, stamp))
            db.execute("UPDATE collectors SET last_seen_at=? WHERE id=?",(stamp,collector["id"]))
            db.commit(); db.close()
            return self.send_json({"accepted": True, "created": created}, 201 if created else 200)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error)}, 400)
        except Exception as error:
            return self.send_json({"error": "ingest failed"}, 500)

    def setup_page(self, error: str = "", status: int = 200) -> None:
        if self.users_exist():return self.redirect("/login")
        message=f"<div class=notice>{html.escape(error)}</div>" if error else ""
        self.send_auth_page("<h1>Create first admin</h1><p class=muted>All users currently have the admin role.</p>"+message+
            "<form method=post action='/setup'><input name=username required maxlength=80 autocomplete=username placeholder='Username'><input type=password name=password required minlength=10 autocomplete=new-password placeholder='Password'><input type=password name=confirm_password required minlength=10 autocomplete=new-password placeholder='Confirm password'><button>Create admin</button></form>",status)

    def setup_submit(self) -> None:
        if self.users_exist():return self.redirect("/login")
        try:
            values=self.form_values();password=values.get("password",[""])[0]
            if password != values.get("confirm_password",[""])[0]:raise ValueError("passwords do not match")
            db=connect(self.db_path)
            try:
                user=create_user(db,values.get("username",[""])[0],password)
                token,_=create_session(db,user["id"])
            finally:db.close()
            return self.redirect("/",f"zh_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800")
        except (ValueError,UnicodeDecodeError) as error:return self.setup_page(str(error),400)
        except Exception:return self.setup_page("Could not create the first admin.",500)

    def login_page(self, error: str = "", status: int = 200) -> None:
        if self.current_user():return self.redirect("/")
        if not self.users_exist():return self.redirect("/setup")
        message=f"<div class=notice>{html.escape(error)}</div>" if error else ""
        self.send_auth_page("<h1>Sign in</h1>"+message+
            "<form method=post action='/login'><input name=username required autocomplete=username placeholder='Username'><input type=password name=password required autocomplete=current-password placeholder='Password'><button>Sign in</button></form>",status)

    def login_submit(self) -> None:
        if not self.users_exist():return self.redirect("/setup")
        try:values=self.form_values()
        except (ValueError,UnicodeDecodeError):return self.login_page("Invalid request.",400)
        db=connect(self.db_path)
        try:
            user=check_credentials(db,values.get("username",[""])[0],values.get("password",[""])[0])
            if not user:return self.login_page("Invalid username or password.",401)
            token,_=create_session(db,user["id"])
        finally:db.close()
        self.redirect("/",f"zh_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800")

    def admin_users(self, message: str = "", error: str = "", status: int = 200) -> None:
        user=self.current_user();csrf=html.escape(user["csrf_token"] if user else "")
        db=connect(self.db_path)
        rows=db.execute("SELECT username,created_at FROM users ORDER BY created_at").fetchall();db.close()
        notice=f"<div class=notice>{html.escape(error or message)}</div>" if error or message else ""
        items="".join(f"<div class=collector-row><strong>{html.escape(row['username'])}</strong><div class=meta>Admin · created {html.escape(row['created_at'])}</div></div>" for row in rows)
        body=("<div class=actions><a class=btn href='/'>Calendar</a><a class=btn href='/admin/collectors'>Collectors</a></div><h1>Users</h1>"
              "<p class=muted>Every user currently has the admin role.</p>"+notice+
              f"<form method=post action='/admin/users'><input type=hidden name=csrf value='{csrf}'><input name=username required maxlength=80 autocomplete=off placeholder='Username'><input type=password name=password required minlength=10 autocomplete=new-password placeholder='Password'><input type=password name=confirm_password required minlength=10 autocomplete=new-password placeholder='Confirm password'><button>Add user</button></form><h2>Administrators</h2>"+items)
        self.send_page(body,status)

    def admin_collectors(self, token: str = "", created_name: str = "", error: str = "",
                         status: int = 200) -> None:
        user=self.current_user();csrf=html.escape(user["csrf_token"] if user else "")
        db=connect(self.db_path)
        rows=db.execute("SELECT id,name,created_at,last_seen_at,disabled FROM collectors ORDER BY created_at DESC").fetchall();db.close()
        message=""
        if token:
            message=(f"<div class=notice><strong>Token for {html.escape(created_name)}</strong>"
                     "<p>Copy it now. It cannot be shown again.</p>"
                     f"<textarea class=token readonly>{html.escape(token)}</textarea></div>")
        elif error:message=f"<div class=notice>{html.escape(error)}</div>"
        items=[]
        for row in rows:
            kind="embedded" if row["id"].startswith("embedded:") else "JWT"
            state="disabled" if row["disabled"] else "active"
            seen=html.escape(row["last_seen_at"] or "never")
            items.append(f"<div class=collector-row><div><strong>{html.escape(row['name'])}</strong><div class=meta>{kind} · {state}</div></div><div class=meta>ID: {html.escape(row['id'])}<br>Created: {html.escape(row['created_at'])}<br>Last seen: {seen}</div></div>")
        body=("<div class=actions><a class=btn href='/'>Calendar</a></div><h1>Collector admin</h1>"
              "<p class=muted>Create a named identity for a remote collector. The JWT is displayed once.</p>"
              f"{message}<form method=post action='/admin/collectors'><input type=hidden name=csrf value='{csrf}'><input name=name required maxlength=120 placeholder='Office workstation'><button>Generate token</button></form>"
              "<h2>Collectors</h2>"+("".join(items) if items else "<p class=muted>No collectors yet.</p>"))
        self.send_page(body,status)

    @staticmethod
    def add_episode(db, item: dict) -> dict:
        if item.get("episode_start_id"):
            return item
        episode = db.execute("""SELECT first_snapshot_id,last_snapshot_id,started_at,ended_at,summary
            FROM segments WHERE pane_id=? AND first_snapshot_id<=? AND last_snapshot_id>=?
            ORDER BY id DESC LIMIT 1""", (item["pane_id"], item["id"], item["id"])).fetchone()
        if episode:
            item.update(episode_start_id=episode[0], episode_end_id=episode[1],
                        episode_started=episode[2], episode_ended=episode[3],
                        episode_summary=episode[4])
        return item

    @staticmethod
    def search_form(query: str = "") -> str:
        return f"<h1>BastionCam</h1><form action='/'><input type=search name=q placeholder='compilation last Tuesday' value='{html.escape(query)}'><button>Search</button></form>"

    def index(self, query: str, range_start: str = "", range_end: str = "") -> None:
        form = self.search_form(query)
        if range_start or range_end:
            db=connect(self.db_path);clauses=[];params=[]
            if range_start:clauses.append("g.ended_at>=?");params.append(range_start)
            if range_end:clauses.append("g.started_at<?");params.append(range_end)
            rows=db.execute(f"""SELECT g.first_snapshot_id id,g.pane_id,g.started_at captured_at,
                g.summary excerpt,g.first_snapshot_id episode_start_id,g.last_snapshot_id episode_end_id,
                g.started_at episode_started,g.ended_at episode_ended,g.summary episode_summary,
                p.session_name,p.tab_name,p.title,p.pane_key,p.cwd,c.name collector_name
                FROM segments g JOIN panes p ON p.id=g.pane_id LEFT JOIN collectors c ON c.id=p.collector_id
                WHERE {' AND '.join(clauses)} ORDER BY g.started_at DESC""",params).fetchall();db.close()
            results=[]
            for row in rows:
                item=dict(row);item.update(score=0,kind="episode");results.append(item)
            return self.send_results(form,results,f"Time range: {range_start or '…'} — {range_end or '…'}","episodes")
        if not query.strip():
            db = connect(self.db_path)
            panes = db.execute("""SELECT p.session_name,p.tab_name,p.title,p.pane_key,p.command,p.cwd,c.name collector_name,
                count(s.id) snapshot_count,max(s.captured_at) latest
                FROM panes p LEFT JOIN snapshots s ON s.pane_id=p.id
                LEFT JOIN collectors c ON c.id=p.collector_id
                GROUP BY p.id ORDER BY latest DESC""").fetchall()
            db.close()
            cards = []
            for pane in panes:
                label = " / ".join(filter(None, [pane["session_name"], pane["tab_name"],
                                                   pane["title"], pane["pane_key"]]))
                details = " · ".join(filter(None, [pane["command"], pane["cwd"]]))
                collector=html.escape(pane["collector_name"] or "unassigned")
                cards.append(f"<div class=result><div class=meta>Collector: {collector} · {html.escape(label)}</div>"
                             f"<p>{pane['snapshot_count']} snapshots · latest {html.escape(pane['latest'] or 'never')}</p>"
                             f"<div class=meta>{html.escape(details)}</div></div>")
            return self.send_page(form + "<h2>Recorded panes</h2>" + "".join(cards))
        text, start, end, interpretation = parse_query(query); db = connect(self.db_path); results: dict[int, dict] = {}
        try:
            if text:
                params: list[object] = [fts_expression(text)]; dates = []
                if start: dates.append("s.captured_at>=?"); params.append(start)
                if end: dates.append("s.captured_at<?"); params.append(end)
                rows = db.execute(f"""SELECT s.id,s.pane_id,s.captured_at,substr(s.content,1,700) excerpt,
                    p.session_name,p.tab_name,p.title,p.pane_key,p.cwd,c.name collector_name,bm25(snapshots_fts) rank
                    FROM snapshots_fts JOIN snapshots s ON s.id=snapshots_fts.rowid JOIN panes p ON p.id=s.pane_id
                    LEFT JOIN collectors c ON c.id=p.collector_id
                    WHERE snapshots_fts MATCH ? {('AND '+' AND '.join(dates)) if dates else ''} ORDER BY rank LIMIT 60""", params).fetchall()
                for row in rows:
                    item = self.add_episode(db, dict(row)); item.update(score=1.0, kind="text")
                    results[row["id"]] = item
                try:
                    if results: raise TimeoutError("exact results available")
                    vector = embed_query(self.ollama_url, self.embed_model, text)
                    params = []; dates = ["g.status='done'", "g.embedding IS NOT NULL"]
                    if start: dates.append("g.ended_at>=?"); params.append(start)
                    if end: dates.append("g.started_at<?"); params.append(end)
                    rows = db.execute(f"""SELECT g.first_snapshot_id id,g.pane_id,g.started_at captured_at,
                        g.summary excerpt,g.embedding,g.first_snapshot_id episode_start_id,g.last_snapshot_id episode_end_id,
                        g.started_at episode_started,g.ended_at episode_ended,g.summary episode_summary,
                        p.session_name,p.tab_name,p.title,p.pane_key,p.cwd,c.name collector_name
                        FROM segments g JOIN panes p ON p.id=g.pane_id LEFT JOIN collectors c ON c.id=p.collector_id
                        WHERE {' AND '.join(dates)} ORDER BY g.id DESC LIMIT 5000""", params).fetchall()
                    for row in rows:
                        score = cosine(vector, decode_embedding(row["embedding"]))
                        if score >= .25:
                            item = dict(row); item.update(score=score, kind="semantic"); results[row["id"]] = item
                except Exception:
                    pass
            else:
                params = []; dates = []
                if start: dates.append("s.captured_at>=?"); params.append(start)
                if end: dates.append("s.captured_at<?"); params.append(end)
                rows = db.execute(f"""SELECT s.id,s.pane_id,s.captured_at,substr(s.content,1,700) excerpt,
                    p.session_name,p.tab_name,p.title,p.pane_key,p.cwd,c.name collector_name
                    FROM snapshots s JOIN panes p ON p.id=s.pane_id LEFT JOIN collectors c ON c.id=p.collector_id
                    {('WHERE '+' AND '.join(dates)) if dates else ''} ORDER BY s.captured_at DESC LIMIT 100""", params).fetchall()
                for row in rows:
                    item=self.add_episode(db,dict(row));item.update(score=0,kind="time");results[row["id"]]=item
        except Exception as error:
            db.close(); return self.send_page(form + f"<p>Search error: {html.escape(str(error))}</p>")
        db.close(); rows = sorted(results.values(), key=lambda x:(x["score"],x["captured_at"]), reverse=True)[:100]
        time_note=f"Time filter: {interpretation} · {start or ''} — {end or ''}" if interpretation else ""
        self.send_results(form,rows,time_note)

    def send_results(self, form: str, rows: list[dict], note: str = "", noun: str = "results") -> None:
        items=[]
        for i,r in enumerate(rows):
            label=" / ".join(filter(None,[r["session_name"],r["tab_name"],r["title"],r["pane_key"]]))
            collector=html.escape(r.get("collector_name") or "unassigned")
            pct=round(r["score"]*100); period=""
            if r.get("episode_started"):
                period=f"<div class=episode>Episode: {html.escape(r['episode_started'])} — {html.escape(r['episode_ended'])}</div>"
            summary=r.get("episode_summary") or r.get("excerpt") or ""; start_id=r.get("episode_start_id") or r["id"]
            items.append(f"<div class=result id=result-{i}><div class=meta>Collector: {collector} · {html.escape(r['captured_at'])} · {html.escape(label)} · <span class=badge>{r['kind']} {pct}%</span></div><div class=meta>cwd: {html.escape(r.get('cwd') or '—')}</div>{period}<p class=summary>{html.escape(summary)}</p><div class=actions><a class=btn href='/snapshot/{r['id']}'>Open moment</a><a class=btn href='/snapshot/{start_id}'>Episode start</a></div></div>")
        time_note=f"<p class=meta>{html.escape(note)}</p>" if note else ""
        self.send_page(form+time_note+f"<p>Found: {len(rows)} {noun}</p>"+"".join(items))

    def player(self, snapshot_id: int) -> None:
        db=connect(self.db_path); row=db.execute("""SELECT s.*,p.session_name,p.tab_name,p.title,p.pane_key,p.cwd,c.name collector_name
            FROM snapshots s JOIN panes p ON p.id=s.pane_id LEFT JOIN collectors c ON c.id=p.collector_id WHERE s.id=?""",(snapshot_id,)).fetchone()
        if not row: db.close(); return self.send_error(404)
        episode=db.execute("SELECT summary,started_at,ended_at FROM segments WHERE pane_id=? AND first_snapshot_id<=? AND last_snapshot_id>=? ORDER BY id DESC LIMIT 1",(row["pane_id"],snapshot_id,snapshot_id)).fetchone();db.close()
        label=" / ".join(filter(None,[row["session_name"],row["tab_name"],row["title"],row["pane_key"]]))
        summary=f"<p class=summary>{html.escape(episode['summary'])}</p>" if episode and episode["summary"] else ""
        controls="""<div class=controls><a class=btn href='/'>Search</a><button id=prev>◀</button><button id=play>▶</button><button id=next>▶|</button><select id=speed><option value=1>1×</option><option value=2>2×</option><option value=5 selected>5×</option><option value=10>10×</option></select><input id=slider type=range min=0 value=0><span id=position></span></div><div class=controls><span id=clock class=clock></span><input id=jump type=datetime-local><span class=muted>Changed lines are highlighted in green</span></div>"""
        script=PLAYER_JS.replace("INITIAL_ID",str(snapshot_id))
        collector=html.escape(row["collector_name"] or "unassigned")
        self.send_page(f"<h1>{html.escape(label)}</h1><div class=meta>Collector: {collector} · cwd: {html.escape(row['cwd'] or '—')}</div>{summary}{controls}<pre id=screen>{html.escape(row['content'])}</pre>{script}")

    def api_snapshot(self, snapshot_id: int) -> None:
        db=connect(self.db_path); row=db.execute("SELECT id,pane_id,captured_at,content FROM snapshots WHERE id=?",(snapshot_id,)).fetchone();db.close()
        if not row:return self.send_error(404)
        self.send_json(dict(row))

    def api_timeline(self, snapshot_id: int) -> None:
        db=connect(self.db_path); row=db.execute("SELECT pane_id FROM snapshots WHERE id=?",(snapshot_id,)).fetchone()
        if not row:db.close();return self.send_error(404)
        rows=db.execute("SELECT id,captured_at FROM snapshots WHERE pane_id=? ORDER BY captured_at,id LIMIT 10000",(row[0],)).fetchall();db.close()
        self.send_json({"pane_id":row[0],"snapshots":[dict(x) for x in rows]})

    def log_message(self, fmt: str, *args) -> None:
        print("http:",fmt%args)


def serve(db_path: str, host: str, port: int, ollama_url: str = "http://127.0.0.1:11434",
          embed_model: str = "nomic-embed-text") -> None:
    App.db_path=db_path; App.ollama_url=ollama_url; App.embed_model=embed_model
    print(f"BastionCam: http://{host}:{port}")
    ThreadingHTTPServer((host,port),App).serve_forever()
