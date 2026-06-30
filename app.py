"""FastAPI web app (U5.1) — the deployable interface over the RAG pipeline.

Routes:
  GET  /         -> minimal HTML chat page (shareable URL)
  POST /chat     -> JSON {answer, citations, snippets, refused}  (frontend contract)
  GET  /health   -> JSON liveness (no DB hit, so health checks don't wake Neon)

Run locally:   uvicorn app:app --reload
Deploy (U6.1): uvicorn app:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.index import db
from src.generation import answer

app = FastAPI(title="Agentic Power-Market Analyst", version="1.0")


class ChatRequest(BaseModel):
    question: str
    k: int = 6


def shape_response(question: str, result: dict) -> dict:
    """Pure shaping of an answer_question result into the /chat JSON contract."""
    return {
        "question": question,
        "answer": result.get("answer", ""),
        "refused": result.get("refused", False),
        "citations": [
            {"index": c.get("index"), "label": c.get("label"),
             "zone": c.get("zone"), "source_url": c.get("source_url")}
            for c in result.get("citations", [])
        ],
        "snippets": [
            {"index": s.get("index"), "label": s.get("label"),
             "zone": s.get("zone"), "snippet": s.get("snippet"),
             "source_url": s.get("source_url")}
            for s in result.get("sources", [])
        ],
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/chat")
def chat(req: ChatRequest) -> dict:
    conn = db.get_connection()
    try:
        result = answer.answer_question(conn, req.question, k=req.k)
    finally:
        conn.close()
    return shape_response(req.question, result)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _PAGE


_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Power-Market Analyst</title>
<style>
 body{font:16px/1.5 system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}
 h1{font-size:1.3rem} .row{display:flex;gap:.5rem;margin:1rem 0}
 input{flex:1;padding:.6rem;border:1px solid #ccc;border-radius:6px;font-size:1rem}
 button{padding:.6rem 1rem;border:0;border-radius:6px;background:#0b6;color:#fff;font-size:1rem;cursor:pointer}
 button:disabled{background:#9cc}
 #answer{white-space:pre-wrap;background:#f6f8f7;border-radius:8px;padding:1rem;min-height:2rem}
 .src{font-size:.85rem;border-left:3px solid #0b6;padding:.3rem .6rem;margin:.4rem 0;background:#fafafa}
 .muted{color:#777;font-size:.85rem}
</style></head><body>
<h1>Agentic Power-Market Analyst</h1>
<p class="muted">Ask about generation/transmission outages in DE-LU, DK1, NO2. Answers are grounded and cited.</p>
<div class="row">
  <input id="q" placeholder="e.g. What gas units are offline in DE-LU?" autofocus>
  <button id="go" onclick="ask()">Ask</button>
</div>
<div id="answer" class="muted">Answers appear here.</div>
<div id="sources"></div>
<script>
async function ask(){
  const q=document.getElementById('q').value.trim(); if(!q) return;
  const btn=document.getElementById('go'), ans=document.getElementById('answer'), src=document.getElementById('sources');
  btn.disabled=true; ans.className=''; ans.textContent='Thinking…'; src.innerHTML='';
  try{
    const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q})});
    const d=await r.json();
    ans.textContent=d.answer||'(no answer)';
    if(d.snippets&&d.snippets.length){
      src.innerHTML='<p class="muted">Sources:</p>';
      d.snippets.forEach(s=>{
        const el=document.createElement('div'); el.className='src';
        const link=s.source_url?` — <a href="${s.source_url}" target="_blank">link</a>`:'';
        el.innerHTML=`[${s.index}] <b>${s.label||'source'}</b> (${s.zone||'?'})${link}<br><span class="muted">${(s.snippet||'').slice(0,200)}</span>`;
        src.appendChild(el);
      });
    }
  }catch(e){ ans.textContent='Error: '+e; }
  finally{ btn.disabled=false; }
}
document.getElementById('q').addEventListener('keydown',e=>{if(e.key==='Enter')ask();});
</script></body></html>"""