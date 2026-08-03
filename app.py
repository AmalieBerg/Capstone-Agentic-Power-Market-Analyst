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

import logging

app = FastAPI(title="Agentic Power-Market Analyst", version="1.0")


class ChatRequest(BaseModel):
    question: str
    k: int = 6
    zone: str | None = None


def shape_response(question: str, result: dict) -> dict:
    """Pure shaping of an answer_question result into the /chat JSON contract."""
    return {
        "question": question,
        "answer": result.get("answer", ""),
        "refused": result.get("refused", False),
        "used_tool": result.get("used_tool", False),
        "tool_result": result.get("tool_result"),
        "citations": [
            {"index": c.get("index"), "label": c.get("label"),
             "zone": c.get("zone"), "source_url": c.get("source_url"),
             "message_id": c.get("message_id")}
            for c in result.get("citations", [])
        ],
        "snippets": [
            {"index": s.get("index"), "label": s.get("label"),
             "zone": s.get("zone"), "snippet": s.get("snippet"),
             "source_url": s.get("source_url"),
             }
            for s in result.get("sources", [])
        ],
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


log = logging.getLogger(__name__)

@app.post("/chat")
def chat(req: ChatRequest) -> dict:
    conn = db.get_connection()
    try:
        try:
            from src.agent import run_agent
            result = run_agent(req.question, conn, k=req.k, zone=req.zone)
        except Exception:
            log.exception("agent layer failed, falling back to retrieval-only")
            result = answer.answer_question(conn, req.question, k=req.k, zone=req.zone)
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
 .examples{display:flex;flex-wrap:wrap;gap:.4rem;margin:.6rem 0 1rem}
 .chip{padding:.35rem .7rem;border:1px solid #0b6;border-radius:999px;background:#fff;color:#0b6;font-size:.85rem;cursor:pointer}
 .chip:hover{background:#eafbf3}
 .badge{display:inline-block;font-size:.75rem;font-weight:600;padding:.15rem .55rem;border-radius:999px;margin-bottom:.5rem}
 .badge-live{background:#e6f7ff;color:#0969da}
 .badge-corpus{background:#eafbf3;color:#0b6}
 .badge-refused{background:#fdeded;color:#c0392b}
</style></head><body>
<h1>Agentic Power-Market Analyst</h1>
<p class="muted">Ask about generation/transmission outages, or current prices and generation, in DE-LU, DK1, NO2. Answers are grounded and cited.</p>
<div class="examples" id="examples">
  <span class="chip" onclick="askExample(this)">What outages affected DE-LU in June?</span>
  <span class="chip" onclick="askExample(this)">What's the current day-ahead price in DK1?</span>
  <span class="chip" onclick="askExample(this)">What gas units are offline in DE-LU?</span>
  <span class="chip" onclick="askExample(this)">How does DE-LU's current price compare to DK1?</span>
</div>
<div class="row">
  <select id="zone">
    <option value="">All zones</option>
    <option value="DE-LU">DE-LU</option>
    <option value="DK1">DK1</option>
    <option value="NO2">NO2</option>
  </select>
</div>
<div class="row">
  <input id="q" placeholder="e.g. What gas units are offline in DE-LU?" autofocus>
  <button id="go" onclick="ask()">Ask</button>
</div>
<div id="badge"></div>
<div id="answer" class="muted">Answers appear here.</div>
<div id="sources"></div>
<script>
function askExample(el){
  document.getElementById('q').value = el.textContent;
  ask();
}
function escapeHtml(s){
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}
function formatAnswer(text){
  let safe = escapeHtml(text);
  safe = safe.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  return safe;
}
async function ask(){
  const q=document.getElementById('q').value.trim(); if(!q) return;
  const btn=document.getElementById('go'), ans=document.getElementById('answer'),
        src=document.getElementById('sources'), badge=document.getElementById('badge');
  btn.disabled=true; ans.className=''; ans.textContent='Thinking…'; src.innerHTML=''; badge.innerHTML='';
  const wakeTimer = setTimeout(() => {
    ans.textContent = 'Still working — the server may be waking up from idle, this can take up to a minute on the first request.';
  }, 4000);
  try{
    const zone = document.getElementById('zone').value;
    const body = {question: q};
    if (zone) body.zone = zone;
    const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d=await r.json();
    clearTimeout(wakeTimer);
    ans.innerHTML = formatAnswer(d.answer || '(no answer)');
    if(d.refused){
      badge.innerHTML='<span class="badge badge-refused">Out of scope — refused</span>';
    } else if(d.used_tool){
      badge.innerHTML='<span class="badge badge-live">Live ENTSO-E data</span>';
    } else {
      badge.innerHTML='<span class="badge badge-corpus">Grounded in corpus</span>';
    }
    if(d.snippets&&d.snippets.length){
      src.innerHTML='<p class="muted">Sources:</p>';
      d.snippets.forEach(s=>{
        const el=document.createElement('div'); el.className='src';
        const link=s.source_url?` — <a href="${s.source_url}" target="_blank">link</a>`:'';
        el.innerHTML=`[${s.index}] <b>${s.label||'source'}</b> (${s.zone||'?'})${link}<br><span class="muted">${(s.snippet||'').slice(0,200)}</span>`;
        src.appendChild(el);
      });
    }
  }catch(e){ clearTimeout(wakeTimer); ans.textContent='Error: '+e; }
  finally{ btn.disabled=false; }
}
document.getElementById('q').addEventListener('keydown',e=>{if(e.key==='Enter')ask();});
</script></body></html>"""