import os
import sqlite3
from contextlib import closing
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "ahmed_ai.sqlite3"
app = FastAPI(title="AHMED AI", version="0.1.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")


def init_db():
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.execute("CREATE TABLE IF NOT EXISTS drafts (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, source TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        db.commit()


@app.on_event("startup")
def startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/drafts")
async def list_drafts():
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT id, kind, source, content, created_at FROM drafts ORDER BY id DESC LIMIT 50").fetchall()
    return [dict(row) for row in rows]


@app.post("/api/generate")
async def generate(kind: str = Form(...), context: str = Form("")):
    if kind not in {"post", "comment", "reply"}:
        raise HTTPException(400, "نوع المحتوى غير مدعوم")
    if not context.strip():
        raise HTTPException(400, "اكتب فكرة أو سياقًا أولًا")
    api_key = os.getenv("AI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(503, "أضف AI_API_KEY في ملف .env لتفعيل التوليد")
    base_url = os.getenv("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("AI_MODEL", "gpt-4o-mini")
    kind_ar = {"post": "منشور فيسبوك", "comment": "تعليق", "reply": "رد على تعليق"}[kind]
    system = "أنت AHMED AI، مساعد كتابة شخصي. اكتب باللهجة المصرية الطبيعية وبأسلوب إنسان عادي، بدون ادعاء أنك أحمد نفسه. لا تخترع وقائع أو وعودًا. أخرج النص النهائي فقط."
    prompt = f"اكتب {kind_ar} بناءً على السياق التالي:\n{context.strip()}"
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(f"{base_url}/chat/completions", headers={"Authorization": f"Bearer {api_key}"}, json={"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}], "temperature": 0.8})
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"].strip()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"مزود الذكاء الاصطناعي رفض الطلب ({exc.response.status_code})")
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        raise HTTPException(502, "تعذر الاتصال بمزود الذكاء الاصطناعي أو قراءة رده")
    with closing(sqlite3.connect(DB_PATH)) as db:
        cur = db.execute("INSERT INTO drafts(kind, source, content) VALUES (?, ?, ?)", (kind, context.strip(), content))
        db.commit()
        draft_id = cur.lastrowid
    return {"id": draft_id, "kind": kind, "content": content}


@app.delete("/api/drafts/{draft_id}")
async def delete_draft(draft_id: int):
    with closing(sqlite3.connect(DB_PATH)) as db:
        cur = db.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
        db.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "المسودة غير موجودة")
    return JSONResponse({"ok": True})
