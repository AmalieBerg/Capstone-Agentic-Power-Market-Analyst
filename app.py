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

import config
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

_ZONE_OPTIONS = "".join(f'<option value="{z}">{z}</option>' for z in config.ZONES)
_ZONE_LIST_TEXT = " &middot; ".join(f'<span class="zonecode">{z}</span>' for z in config.ZONES)

_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Power-Market Analyst</title>
<style>
:root{
  color-scheme: dark;
  --bg:#0F1720; --panel:#18232E; --panel-2:#1E2B38; --border:#2A3A48;
  --text:#E7ECF1; --muted:#8A97A6; --teal:#2DD4BF; --amber:#F5A623;
  --green:#34D399; --red:#F87171; --mono:'IBM Plex Mono',ui-monospace,'SF Mono',Menlo,Consolas,monospace;
  --sans:-apple-system,BlinkMacSystemFont,'Segoe UI',Inter,Roboto,sans-serif;
}
*{box-sizing:border-box}
body{
  font-family:var(--sans); background:var(--bg); color:var(--text);
  max-width:760px; margin:0 auto; padding:2.5rem 1.25rem 4rem;
  line-height:1.55;
}
.topbar{display:flex; align-items:center; gap:.6rem; margin-bottom:.3rem}
.pulse{
  width:9px; height:9px; border-radius:50%; background:var(--teal); flex:none;
  box-shadow:0 0 0 0 rgba(45,212,191,.6); animation:pulse 2.2s infinite;
}
@keyframes pulse{
  0%{box-shadow:0 0 0 0 rgba(45,212,191,.55)}
  70%{box-shadow:0 0 0 8px rgba(45,212,191,0)}
  100%{box-shadow:0 0 0 0 rgba(45,212,191,0)}
}
@media (prefers-reduced-motion: reduce){ .pulse{ animation:none } }
h1{
  font-family:var(--mono); font-size:1.15rem; font-weight:600; letter-spacing:.02em;
  margin:0; color:var(--text);
}
.subtitle{
  font-family:var(--mono); font-size:.78rem; color:var(--muted); letter-spacing:.03em;
  margin:.35rem 0 1.6rem; padding-left:1.35rem;
}
.subtitle .zonecode{color:var(--teal)}

.panel{
  background:var(--panel); border:1px solid var(--border); border-radius:10px;
  padding:1rem 1.1rem; margin-bottom:1rem;
}

.controls-row{display:flex; gap:.6rem; align-items:center}
.zone-select{
  font-family:var(--mono); font-size:.82rem; background:var(--panel-2); color:var(--text);
  border:1px solid var(--border); border-radius:6px; padding:.5rem 2rem .5rem .7rem;
  appearance:none; -webkit-appearance:none; cursor:pointer; min-width:9.5rem;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%238A97A6'/%3E%3C/svg%3E");
  background-repeat:no-repeat; background-position:right .8rem center;
}
.zone-select:focus{outline:2px solid var(--teal); outline-offset:1px}

.query-row{
  display:flex; align-items:center; gap:.5rem; margin-top:.7rem;
  background:var(--panel-2); border:1px solid var(--border); border-radius:8px;
  padding:.15rem .15rem .15rem .9rem;
}
.prompt-glyph{font-family:var(--mono); color:var(--teal); font-weight:600}
.query-row input{
  flex:1; background:transparent; border:0; color:var(--text); font-size:.95rem;
  font-family:var(--sans); padding:.65rem 0;
}
.query-row input::placeholder{color:var(--muted)}
.query-row input:focus{outline:none}
.query-row button{
  font-family:var(--mono); font-size:.8rem; font-weight:600; letter-spacing:.02em;
  padding:.6rem 1.1rem; border:0; border-radius:6px; background:var(--teal);
  color:#08201C; cursor:pointer; white-space:nowrap;
}
.query-row button:hover{background:#5EEAD4}
.query-row button:disabled{background:#3A4A54; color:var(--muted); cursor:default}
.query-row button:focus-visible, .chip:focus-visible{outline:2px solid var(--teal); outline-offset:2px}

.examples{display:flex; flex-wrap:wrap; gap:.5rem; margin-top:.7rem}
.chip{
  font-family:var(--mono); font-size:.74rem; padding:.4rem .75rem;
  border:1px solid var(--border); border-radius:999px; background:transparent;
  color:var(--muted); cursor:pointer; transition:border-color .15s, color .15s;
}
.chip:hover{border-color:var(--teal); color:var(--teal)}

.badge-row{
  display:flex; align-items:center; gap:.5rem; font-family:var(--mono);
  font-size:.72rem; font-weight:600; letter-spacing:.03em; text-transform:uppercase;
  margin-bottom:.6rem;
}
.badge-row .dot{width:7px; height:7px; border-radius:50%; flex:none}
.badge-live .dot{background:var(--amber)} .badge-live{color:var(--amber)}
.badge-corpus .dot{background:var(--green)} .badge-corpus{color:var(--green)}
.badge-refused .dot{background:var(--red)} .badge-refused{color:var(--red)}

.answer-panel{border-left:3px solid var(--border)}
.answer-panel.state-corpus{border-left-color:var(--green)}
.answer-panel.state-live{border-left-color:var(--amber)}
.answer-panel.state-refused{border-left-color:var(--red)}
#answer{white-space:pre-wrap; font-size:.95rem; color:var(--text)}
#answer.muted{color:var(--muted)}

.sources-label{
  font-family:var(--mono); font-size:.7rem; color:var(--muted); letter-spacing:.05em;
  text-transform:uppercase; margin:1.1rem 0 .5rem;
}
.src{
  border:1px solid var(--border); border-left:3px solid var(--teal); border-radius:6px;
  padding:.6rem .75rem; margin-bottom:.5rem; background:var(--panel-2);
}
.src b{font-size:.88rem} .src .zone-tag{
  font-family:var(--mono); font-size:.68rem; color:var(--teal); margin-left:.3rem;
}
.src a{color:var(--teal); text-decoration:none; font-size:.8rem}
.src a:hover{text-decoration:underline}
.src .snippet{color:var(--muted); font-size:.82rem; display:block; margin-top:.3rem}

@media (max-width:480px){
  .controls-row{flex-wrap:wrap}
  .zone-select{width:100%}
  .query-row{flex-wrap:wrap}
  .query-row button{width:100%; margin-top:.4rem}
}
</style></head><body>

<div class="topbar"><span class="pulse"></span><h1>AGENTIC POWER-MARKET ANALYST</h1></div>
<p class="subtitle">live grid intelligence &middot; __ZONE_LIST__</p>

<div class="panel">
  <div class="controls-row">
    <select id="zone" class="zone-select">
      <option value="">ALL ZONES</option>
      __ZONE_OPTIONS__
    </select>
  </div>
  <div class="query-row">
    <span class="prompt-glyph">&gt;</span>
    <input id="q" placeholder="ask about outages, or current prices and generation&hellip;" autofocus>
    <button id="go" onclick="ask()">ASK</button>
  </div>
  <div class="examples" id="examples">
    <span class="chip" onclick="askExample(this)">What outages affected DE-LU in June?</span>
    <span class="chip" onclick="askExample(this)">What's the current day-ahead price in DK1?</span>
    <span class="chip" onclick="askExample(this)">What gas units are offline in DE-LU?</span>
    <span class="chip" onclick="askExample(this)">How does DE-LU's current price compare to DK1?</span>
  </div>
</div>

<div class="panel answer-panel" id="answer-panel">
  <div id="badge"></div>
  <div id="answer" class="muted">Answers appear here.</div>
</div>
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
  safe = safe.replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>');
  return safe;
}
async function ask(){
  const q=document.getElementById('q').value.trim(); if(!q) return;
  const btn=document.getElementById('go'), ans=document.getElementById('answer'),
        src=document.getElementById('sources'), badge=document.getElementById('badge'),
        panel=document.getElementById('answer-panel');
  btn.disabled=true; ans.className='muted'; ans.textContent='Thinking\\u2026'; src.innerHTML=''; badge.innerHTML='';
  panel.className='panel answer-panel';
  const wakeTimer = setTimeout(() => {
    ans.textContent = 'Still working \\u2014 the server may be waking up from idle, this can take up to a minute on the first request.';
  }, 4000);
  try{
    const zone = document.getElementById('zone').value;
    const body = {question: q};
    if (zone) body.zone = zone;
    const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d=await r.json();
    clearTimeout(wakeTimer);
    ans.className='';
    ans.innerHTML = formatAnswer(d.answer || '(no answer)');
    if(d.refused){
      badge.innerHTML='<div class="badge-row badge-refused"><span class="dot"></span>Out of scope \\u2014 refused</div>';
      panel.className='panel answer-panel state-refused';
    } else if(d.used_tool){
      badge.innerHTML='<div class="badge-row badge-live"><span class="dot"></span>Live ENTSO-E data</div>';
      panel.className='panel answer-panel state-live';
    } else {
      badge.innerHTML='<div class="badge-row badge-corpus"><span class="dot"></span>Grounded in corpus</div>';
      panel.className='panel answer-panel state-corpus';
    }
    if(d.snippets&&d.snippets.length){
      src.innerHTML='<div class="sources-label">Sources</div>';
      d.snippets.forEach(s=>{
        const el=document.createElement('div'); el.className='src';
        const link=s.source_url?` \\u2014 <a href="${s.source_url}" target="_blank">link \\u2197</a>`:'';
        el.innerHTML=`<b>${s.label||'source'}</b><span class="zone-tag">${s.zone||'?'}</span>${link}<span class="snippet">${(s.snippet||'').slice(0,200)}</span>`;
        src.appendChild(el);
      });
    }
  }catch(e){ clearTimeout(wakeTimer); ans.className=''; ans.textContent='Error: '+e; }
  finally{ btn.disabled=false; }
}
document.getElementById('q').addEventListener('keydown',e=>{if(e.key==='Enter')ask();});
</script></body></html>"""

_PAGE = _PAGE.replace("__ZONE_OPTIONS__", _ZONE_OPTIONS)
_PAGE = _PAGE.replace("__ZONE_LIST__", _ZONE_LIST_TEXT)