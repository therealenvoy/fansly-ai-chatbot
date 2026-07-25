"""
Dashboard web server — SPA + REST API for the Fansly AI bot.
Sidebar navigation, Linear-dark aesthetic, proper UX hierarchy per section.
"""
import json, os, logging, yaml
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, TYPE_CHECKING
from urllib.parse import parse_qs

from ..sequences.models import Sequence, SequenceTrigger, SequenceStep, FanSequenceProgress, StepStatus

logger = logging.getLogger("fansly-bot.dashboard")
if TYPE_CHECKING:
    from ..bot import FanslyBot

PERSONA_DIR = "/data/config/creators"
BRAND_BIBLE_PATH = "/data/config/brand_bible.md"

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Sunny Charm</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#08090a;--panel:#0f1011;--surf:#191a1b;--hover:rgba(255,255,255,0.04);--tx:#f7f8f8;--tx2:#8a8f98;--tx3:#62666d;--accent:#7170ff;--ahover:#828fff;--abg:rgba(113,112,255,0.12);--border:rgba(255,255,255,0.08);--bsub:rgba(255,255,255,0.05);--green:#27a644}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--tx);-webkit-font-smoothing:antialiased;height:100vh;overflow:hidden;display:flex}
/* SIDEBAR */
aside{width:220px;min-width:220px;background:var(--panel);border-right:1px solid var(--bsub);display:flex;flex-direction:column;padding:0}
aside .logo{height:48px;display:flex;align-items:center;padding:0 16px;gap:8px;border-bottom:1px solid var(--bsub)}
aside .logo .dot{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 6px rgba(39,166,68,0.4)}
aside .logo .dot.off{background:#f87171;box-shadow:0 0 6px rgba(248,113,113,0.4)}
aside .logo span{font-size:13px;font-weight:600;letter-spacing:-0.13px}
aside nav{flex:1;padding:8px}
aside nav a{display:flex;align-items:center;gap:10px;padding:8px 12px;border-radius:6px;font-size:13px;font-weight:500;color:var(--tx3);text-decoration:none;cursor:pointer;transition:all .12s;margin-bottom:2px}
aside nav a:hover{color:var(--tx2);background:var(--hover)}
aside nav a.active{color:var(--tx);background:var(--abg)}
aside nav a .ico{font-size:15px;width:20px;text-align:center}
aside .footer{padding:12px;border-top:1px solid var(--bsub);font-size:11px;color:var(--tx3)}
aside .footer a{color:var(--tx3);text-decoration:none;display:block;padding:4px 8px;border-radius:4px;font-size:11px}
aside .footer a:hover{color:var(--tx2);background:var(--hover)}
/* MAIN */
main{flex:1;display:flex;flex-direction:column;overflow:hidden}
.topbar{height:48px;min-height:48px;background:var(--panel);border-bottom:1px solid var(--bsub);display:flex;align-items:center;padding:0 24px;justify-content:space-between}
.topbar h2{font-size:14px;font-weight:600;letter-spacing:-0.13px}
.topbar .meta{font-size:12px;color:var(--tx3)}
.content{flex:1;overflow-y:auto;padding:24px}
/* CARDS & GRIDS */
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}
.card{background:var(--surf);border:1px solid var(--border);border-radius:10px;padding:16px 18px}
.card h3{font-size:10px;font-weight:500;color:var(--tx3);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px}
.card .v{font-size:22px;font-weight:600;font-variant-numeric:tabular-nums;letter-spacing:-0.24px}
.v.up{color:var(--green)}.v.warn{color:#f59e0b}.v.bad{color:#f87171}
/* TABLE */
.panel{background:var(--surf);border:1px solid var(--border);border-radius:10px;overflow:hidden}
.panel table{width:100%;border-collapse:collapse}
.panel th{text-align:left;padding:8px 14px;font-size:10px;font-weight:500;color:var(--tx3);text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid var(--border);background:var(--panel)}
.panel td{padding:8px 14px;font-size:12px;color:var(--tx2);border-bottom:1px solid var(--bsub);font-variant-numeric:tabular-nums}
.panel tr:hover td{background:var(--hover)}
.panel tr:last-child td{border-bottom:none}
/* BADGE */
.badge{display:inline-flex;align-items:center;gap:4px;padding:1px 8px;border-radius:9999px;font-size:11px;font-weight:500}
.badge::before{content:'';width:5px;height:5px;border-radius:50%;flex-shrink:0}
.badge.whale{background:var(--abg);color:#a5a3ff}.badge.whale::before{background:var(--accent)}
.badge.avg{background:rgba(39,166,68,0.12);color:#4ade80}.badge.avg::before{background:var(--green)}
.badge.low{background:var(--hover);color:var(--tx3)}.badge.low::before{background:var(--tx3)}
.badge.rapport{background:rgba(96,165,250,0.1);color:#93c5fd}.badge.rapport::before{background:#60a5fa}
.badge.tease{background:rgba(232,121,249,0.1);color:#e879f9}.badge.tease::before{background:#e879f9}
.badge.offer{background:rgba(248,113,113,0.1);color:#f87171}.badge.offer::before{background:#f87171}
.badge.handle{background:rgba(251,191,36,0.1);color:#fbbf24}.badge.handle::before{background:#fbbf24}
.badge.close{background:rgba(39,166,68,0.12);color:#4ade80}.badge.close::before{background:var(--green)}
/* VAULT */
.media-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.media-card{background:var(--surf);border:1px solid var(--border);border-radius:10px;padding:16px 12px;text-align:center;transition:background .15s;cursor:default}
.media-card:hover{background:var(--hover)}
.media-card .ico{font-size:26px;margin-bottom:8px}
.media-card .name{font-size:11px;color:var(--tx2);word-break:break-word;line-height:1.3}
.media-card .size{font-size:10px;color:var(--tx3);margin-top:4px}
/* EMPTY */
.empty{padding:64px 24px;text-align:center;color:var(--tx3)}
.empty .ico{font-size:28px;margin-bottom:12px;opacity:.3}
.empty p{font-size:13px}
/* SCRIPTS */
.cat{margin-bottom:18px}
.cat h4{font-size:11px;font-weight:500;color:var(--accent);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px}
/* SETTINGS */
.block{margin-bottom:24px}
.block h3{font-size:14px;font-weight:600;margin-bottom:10px;letter-spacing:-0.13px}
label{display:block;font-size:10px;font-weight:500;color:var(--tx3);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px}
input,textarea,select{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px 10px;color:var(--tx);font-family:'JetBrains Mono','SF Mono',monospace;font-size:12px;resize:vertical}
input:focus,textarea:focus,select:focus{outline:none;border-color:var(--accent)}
textarea{min-height:200px;line-height:1.5}
select{font-family:'Inter',sans-serif;font-size:12px}
.btn{background:var(--accent);color:#fff;border:none;border-radius:6px;padding:8px 16px;font-family:'Inter',sans-serif;font-size:12px;font-weight:500;cursor:pointer;transition:background .15s,transform .1s}
.btn:hover{background:var(--ahover)}.btn:active{transform:scale(.96)}
.btn-ghost{background:var(--hover);color:var(--tx2);border:1px solid var(--border);border-radius:6px;padding:6px 12px;font-family:'Inter',sans-serif;font-size:11px;font-weight:500;cursor:pointer;transition:all .15s}
.btn-ghost:hover{color:var(--tx);border-color:rgba(255,255,255,.12)}
.row{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.done{color:var(--green);font-size:11px;font-weight:500;display:none;align-items:center;gap:4px}
.done::before{content:'\2713 '}
#conn-result{font-size:11px;font-weight:500}
.g3{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
@media(max-width:768px){aside{display:none}}
/* FAN DETAIL DRAWER */
.drawer{position:fixed;top:0;right:-520px;width:520px;max-width:92vw;height:100vh;background:var(--panel);border-left:1px solid var(--border);z-index:50;transition:right .2s ease;display:flex;flex-direction:column}
.drawer.open{right:0}
.drawer .dhead{padding:14px 18px;border-bottom:1px solid var(--bsub);display:flex;align-items:center;justify-content:space-between}
.drawer .dhead h3{font-size:14px;font-weight:600;letter-spacing:-0.13px}
.drawer .dclose{background:none;border:none;color:var(--tx3);font-size:18px;cursor:pointer;padding:4px 8px}
.drawer .dclose:hover{color:var(--tx)}
.drawer .dbody{flex:1;overflow-y:auto;padding:18px}
.dsec{margin-bottom:18px}
.dsec h4{font-size:10px;font-weight:500;color:var(--tx3);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px}
.fact-list{list-style:none}
.fact-list li{font-size:12px;color:var(--tx2);padding:6px 10px;background:var(--surf);border:1px solid var(--bsub);border-radius:6px;margin-bottom:6px}
.fact-list li::before{content:'\U0001f9e0 ';font-size:11px}
.msg{display:flex;margin-bottom:8px}
.msg .bubble{max-width:85%;padding:8px 12px;border-radius:10px;font-size:12px;line-height:1.4}
.msg.fan .bubble{background:var(--surf);border:1px solid var(--bsub);color:var(--tx2)}
.msg.creator{justify-content:flex-end}
.msg.creator .bubble{background:var(--abg);color:var(--tx)}
.msg .who{font-size:9px;color:var(--tx3);margin-top:2px}
.msgwrap{display:flex;flex-direction:column}
.msg.fan .msgwrap{align-items:flex-start}
.msg.creator .msgwrap{align-items:flex-end}
.pill-row{display:flex;flex-wrap:wrap;gap:6px}
.pill{font-size:11px;padding:2px 10px;border-radius:9999px;background:var(--surf);border:1px solid var(--bsub);color:var(--tx2)}
tr.clickable{cursor:pointer}
tr.clickable:hover td{background:var(--hover)}
</style>
</head>
<body>
<aside>
<div class="logo"><span class="dot" id="dot"></span><span>Sunny Charm</span></div>
<nav>
<a class="active" data-tab="funnel" onclick="navTo('funnel')"><span class="ico">&#9889;</span>Funnel</a>
<a data-tab="vault" onclick="navTo('vault')"><span class="ico">&#128193;</span>Vault</a>
<a data-tab="fans" onclick="navTo('fans')"><span class="ico">&#128101;</span>Fans</a>
<a data-tab="scripts" onclick="navTo('scripts')"><span class="ico">&#128221;</span>Scripts</a>
<a data-tab="kpis" onclick="navTo('kpis')"><span class="ico">&#128202;</span>KPIs</a>
<a data-tab="sequences" onclick="navTo('sequences')"><span class="ico">&#128196;</span>Sequences</a>
<a data-tab="settings" onclick="navTo('settings')"><span class="ico">&#9881;</span>Settings</a>
</nav>
<div class="footer"><a href="/health" target="_blank">API Health</a></div>
</aside>
<main>
<div class="topbar"><h2 id="page-title">Funnel</h2><span class="meta" id="page-meta"></span></div>
<div class="content" id="content"></div>
</main>
<div class="drawer" id="drawer">
<div class="dhead"><h3 id="dtitle">Fan</h3><button class="dclose" onclick="closeDrawer()">&times;</button></div>
<div class="dbody" id="dbody"></div>
</div>
<script>
function navTo(tab){
  document.querySelectorAll('aside nav a').forEach(a=>a.classList.remove('active'));
  document.querySelector('a[data-tab="'+tab+'"]').classList.add('active');
  var titles={'funnel':'Funnel','vault':'Vault','fans':'Fans','scripts':'Scripts','kpis':'KPIs','sequences':'PPV Sequences','settings':'Settings'};
  document.getElementById('page-title').textContent=titles[tab]||tab;
  document.getElementById('page-meta').textContent='';
  if(tab==='funnel')loadFunnel();if(tab==='vault')loadVault();if(tab==='fans')loadFans();
  if(tab==='scripts')loadScripts();if(tab==='kpis')loadKPIs();if(tab==='sequences')loadSequences();if(tab==='settings')loadSettings();
}
async function F(u){try{var r=await fetch(u);return await r.json()}catch(e){return null}}
function B(c,t){return'<span class="badge '+c+'">'+t+'</span>'}
function ft(t){if(!t)return'\u2014';var d=new Date(t+'Z'),n=new Date(),s=Math.floor((n-d)/1000);if(s<60)return s+'s';if(s<3600)return Math.floor(s/60)+'m';return Math.floor(s/3600)+'h'}

function loadFunnel(){
  var c=document.getElementById('content');
  F('/api/conversations').then(function(d){
    if(!d||!d.fans||!d.fans.length){c.innerHTML='<div class="empty"><div class="ico">&#9889;</div><p>Waiting for messages</p></div>';return}
    var h='<div class="panel"><table><thead><tr><th>Fan</th><th>Tier</th><th>Stage</th><th>Level</th><th>Msgs</th><th>Facts</th><th>Active</th></tr></thead><tbody>';
    d.fans.forEach(function(f){h+='<tr class="clickable" onclick="fanDetail(\''+f.fan_id+'\')"><td style="color:var(--tx)">'+(f.display_name||f.fan_id.slice(0,10))+'</td><td>'+B(f.spend_tier==='whale'?'whale':f.spend_tier==='average'?'avg':'low',f.spend_tier)+'</td><td>'+B(f.funnel_stage,f.funnel_stage)+(f.cooldown?' <span style="color:var(--tx3);font-size:10px">&#9924;</span>':'')+'</td><td>'+B('avg','L'+(f.spiral_level||0))+'</td><td>'+f.message_count+'</td><td>'+(f.fact_count||0)+'</td><td>'+ft(f.last_activity)+'</td></tr>'});
    h+='</tbody></table></div>';c.innerHTML=h;
  });
}
setInterval(function(){if(document.querySelector('a[data-tab="funnel"].active')&&!document.getElementById('drawer').classList.contains('open'))loadFunnel()},15000);

function fanDetail(fanId){
  var dr=document.getElementById('drawer');dr.classList.add('open');
  document.getElementById('dtitle').textContent='Loading...';
  document.getElementById('dbody').innerHTML='';
  F('/api/conversations/'+fanId).then(function(d){
    if(!d){document.getElementById('dtitle').textContent='Error';return}
    var p=d.profile||{};
    document.getElementById('dtitle').textContent=p.display_name||d.fan_id.slice(0,12);
    var h='';
    // Profile pills
    h+='<div class="dsec"><h4>Profile</h4><div class="pill-row">';
    h+='<span class="pill">'+(p.spend_tier||'unknown')+'</span>';
    h+='<span class="pill">$'+((p.total_spent||0).toFixed(0))+' spent</span>';
    h+='<span class="pill">'+(p.purchase_count||0)+' buys</span>';
    if(p.occupation)h+='<span class="pill">'+p.occupation+'</span>';
    if(d.funnel_stage)h+='<span class="pill">'+d.funnel_stage+'</span>';
    h+='</div></div>';
    // PPV Sequence progress
    if(d.sequences&&d.sequences.length){
      h+='<div class="dsec"><h4>PPV Sequences</h4>';
      d.sequences.forEach(function(sq){
        h+='<div style="background:var(--surf);border:1px solid var(--bsub);border-radius:8px;padding:10px;margin-bottom:8px">';
        h+='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">';
        h+='<span style="font-size:12px;font-weight:500">'+esc(sq.sequence_name)+'</span>';
        var pct=sq.total_steps>0?Math.round(sq.current_step/sq.total_steps*100):0;
        h+='<span style="font-size:10px;color:var(--tx3)">'+sq.current_step+'/'+sq.total_steps+'</span></div>';
        h+='<div style="height:4px;background:var(--bg);border-radius:2px;overflow:hidden"><div style="height:100%;width:'+pct+'%;background:var(--accent);border-radius:2px"></div></div>';
        h+='<div style="font-size:10px;color:var(--tx3);margin-top:4px">'+sq.status+(sq.last_sent_at?' &middot; '+ft(sq.last_sent_at):'')+'</div></div>';
      });
      h+='</div>';
    }
    // Remembered facts
    h+='<div class="dsec"><h4>Remembered ('+(d.facts||[]).length+' facts)</h4>';
    if(d.facts&&d.facts.length){h+='<ul class="fact-list">';d.facts.forEach(function(f){h+='<li>'+f+'</li>'});h+='</ul>'}
    else h+='<p style="font-size:12px;color:var(--tx3)">No facts learned yet — the bot extracts facts from every 3rd fan message.</p>';
    h+='</div>';
    // Writing style mirror
    if(d.style&&d.style.formality!=='unknown'){
      h+='<div class="dsec"><h4>Style Mirror</h4><div class="pill-row">';
      h+='<span class="pill">'+d.style.formality+'</span>';
      h+='<span class="pill">~'+d.style.avg_length+' chars</span>';
      h+='<span class="pill">'+d.style.emoji_rate+' emoji/msg</span>';
      if(d.style.uses_abbreviations)h+='<span class="pill">abbrev</span>';
      (d.style.slang||[]).forEach(function(x){h+='<span class="pill" style="border-color:rgba(113,112,255,.3);color:#a5a3ff">'+x+'</span>'});
      h+='</div></div>';
    }
    // Preferences & limits
    if((d.preferences&&d.preferences.length)||(d.hard_limits&&d.hard_limits.length)){
      h+='<div class="dsec"><h4>Preferences &amp; Boundaries</h4><div class="pill-row">';
      (d.preferences||[]).forEach(function(x){h+='<span class="pill">'+x+'</span>'});
      (d.hard_limits||[]).forEach(function(x){h+='<span class="pill" style="border-color:rgba(248,113,113,.3);color:#f87171">'+x+'</span>'});
      h+='</div></div>';
    }
    // Message history
    h+='<div class="dsec"><h4>Conversation ('+(d.message_count_stored||0)+' stored)</h4>';
    if(d.messages&&d.messages.length){
      d.messages.forEach(function(m){
        var who=m.sender==='fan'?'Fan':'You';
        h+='<div class="msg '+(m.sender==='fan'?'fan':'creator')+'\"><div class="msgwrap"><div class="bubble">'+esc(m.content)+'</div><div class="who">'+who+(m.created_at?' &middot; '+ft(m.created_at):'')+'</div></div></div>';
      });
    } else h+='<p style="font-size:12px;color:var(--tx3)">No stored messages yet.</p>';
    h+='</div>';
    document.getElementById('dbody').innerHTML=h;
  });
}
function closeDrawer(){document.getElementById('drawer').classList.remove('open')}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

function loadVault(){
  var c=document.getElementById('content');
  F('/api/vault').then(function(d){
    if(!d||!d.files||!d.files.length){c.innerHTML='<div class="empty"><div class="ico">&#128193;</div><p>Upload content to /data/videos</p></div>';return}
    var h='<div class="media-grid">';d.files.forEach(function(f){var i=f.type==='video'?'&#127916;':f.type==='image'?'&#128444;':'&#128196;';h+='<div class="media-card"><div class="ico">'+i+'</div><div class="name">'+f.name+'</div><div class="size">'+f.size+'</div></div>'});h+='</div>';c.innerHTML=h;
  });
}

function loadFans(){
  var c=document.getElementById('content');
  F('/api/fans').then(function(d){
    if(!d||!d.fans||!d.fans.length){c.innerHTML='<div class="empty"><div class="ico">&#128101;</div><p>No fan profiles yet</p></div>';return}
    var h='<div class="panel"><table><thead><tr><th>Fan</th><th>Tier</th><th>Spent</th><th>Buys</th><th>Stage</th><th>Preferences</th></tr></thead><tbody>';
    d.fans.forEach(function(f){h+='<tr><td style="color:var(--tx)">'+(f.display_name||f.fan_id.slice(0,10))+'</td><td>'+B(f.spend_tier==='whale'?'whale':f.spend_tier==='average'?'avg':'low',f.spend_tier)+'</td><td>$'+((f.total_spent||0).toFixed(0))+'</td><td>'+f.purchase_count+'</td><td>'+(f.relationship_stage||'new')+'</td><td style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+((f.preferences||[]).join(', ')||'\u2014')+'</td></tr>'});
    h+='</tbody></table></div>';c.innerHTML=h;
  });
}

function loadScripts(){
  var c=document.getElementById('content');
  F('/api/scripts').then(function(d){
    if(!d||!d.scripts||!d.scripts.length){c.innerHTML='<div class="empty"><div class="ico">&#128221;</div><p>No scripts loaded</p></div>';return}
    var by={};d.scripts.forEach(function(s){if(!by[s.category])by[s.category]=[];by[s.category].push(s)});
    var h='';Object.entries(by).forEach(function(e){var cat=e[0],ss=e[1];h+='<div class="cat"><h4>'+cat+'</h4><div class="panel"><table><thead><tr><th>Name</th><th>Msgs</th><th>Description</th></tr></thead><tbody>';
    ss.forEach(function(s){h+='<tr><td style="color:var(--tx)">'+s.name+'</td><td>'+s.message_count+'</td><td>'+s.description+'</td></tr>'});
    h+='</tbody></table></div></div>'});
    c.innerHTML=h||'<div class="empty"><div class="ico">&#128221;</div><p>No scripts</p></div>';
  });
}

function loadKPIs(){
  var c=document.getElementById('content');
  F('/api/kpis').then(function(d){
    if(!d){c.innerHTML='<div class="empty"><div class="ico">&#128202;</div><p>No data</p></div>';return}
    var cards=[{l:'Chatting Ratio',v:(d.chatting_ratio||0).toFixed(1)+':1',c:d.chatting_ratio>=6?'up':d.chatting_ratio>=4?'warn':'bad'},{l:'PPV Unlock Rate',v:(d.ppv_unlock_rate||0).toFixed(1)+'%',c:d.ppv_unlock_rate>=8?'up':d.ppv_unlock_rate>=5?'warn':'bad'},{l:'Avg Order Value',v:'$'+(d.aov||0).toFixed(0),c:d.aov>=30?'up':'warn'},{l:'Script Completion',v:(d.script_completion_rate||0).toFixed(1)+'%',c:d.script_completion_rate>=18?'up':'warn'},{l:'Health',v:(d.health_label||'N/A').toUpperCase(),c:d.health_label==='elite'||d.health_label==='healthy'?'up':'warn'},{l:'Active Fans',v:d.active_fans||0,c:'up'}];
    c.innerHTML='<div class="cards">'+cards.map(function(card){return'<div class="card"><h3>'+card.l+'</h3><div class="v '+card.c+'\">'+card.v+'</div></div>'}).join('')+'</div>';
  });
}

function loadSettings(){
  var c=document.getElementById('content');
  var h='<div class="block"><h3>API Connection</h3><div class="g3" id="api-status">Loading...</div><div style="margin-top:10px"><button class="btn-ghost" onclick="testConn()">Test Connection</button> <span id="conn-result"></span></div></div>';
  h+='<div class="block"><h3>Persona</h3><div class="row"><select id="psel" onchange="loadPersona()"><option value="sunny_charm">sunny_charm</option></select><button class="btn-ghost" onclick="loadPersona()">Load</button><span class="done" id="psaved">Saved</span></div><label>config/creators/{model}.yaml</label><textarea id="ped" placeholder="tone: flirty&#10;signature_phrases:&#10;  - hey babe"></textarea><div style="margin-top:10px"><button class="btn" onclick="savePersona()">Save Persona</button></div></div>';
  h+='<div class="block"><h3>Brand Bible</h3><label>config/brand_bible.md</label><textarea id="bed" placeholder="# Brand Bible&#10;&#10;## Voice..."></textarea><div style="margin-top:10px"><button class="btn" onclick="saveBible()">Save Brand Bible</button> <span class="done" id="bsaved">Saved</span></div></div>';
  c.innerHTML=h;loadConn();loadPersona();loadBrandBible();
}
function loadConn(){F('/api/connection').then(function(d){var el=document.getElementById('api-status');if(!d){el.innerHTML='<div class="card"><h3>Error</h3><div style="font-size:12px;color:#f87171">Failed</div></div>';return}el.innerHTML='<div class="card"><h3>Account</h3><div style="font-size:12px">'+d.account_id+'</div></div><div class="card"><h3>API</h3><div class="v '+(d.connected?'up':'bad')+'" style="font-size:16px">'+(d.connected?'Connected':'Offline')+'</div></div><div class="card"><h3>Endpoint</h3><div style="font-size:11px;color:var(--tx3)">v1.apifansly.com</div></div>'})}
function testConn(){var el=document.getElementById('conn-result');el.textContent='Testing\u2026';el.style.color='var(--tx3)';F('/api/connection?test=1').then(function(d){var ok=d&&d.connected;el.textContent=ok?'Connected':'Failed: '+(d.error||'unknown');el.style.color=ok?'var(--green)':'#f87171';loadConn()})}
function loadPersona(){var m=document.getElementById('psel').value;F('/api/persona?creator='+m).then(function(d){document.getElementById('ped').value=d&&d.yaml||''})}
function savePersona(){var m=document.getElementById('psel').value,y=document.getElementById('ped').value;fetch('/api/persona?creator='+m,{method:'POST',body:y}).then(function(r){var el=document.getElementById('psaved');if(r.ok){el.style.display='flex';setTimeout(function(){el.style.display='none'},2000)}})}
function loadBrandBible(){F('/api/brand-bible').then(function(d){document.getElementById('bed').value=d&&d.content||''})}
function saveBible(){var c=document.getElementById('bed').value;fetch('/api/brand-bible',{method:'POST',body:c}).then(function(r){var el=document.getElementById('bsaved');if(r.ok){el.style.display='flex';setTimeout(function(){el.style.display='none'},2000)}})}

// ═══ PPV SEQUENCES ════════════════════════════════════
function loadSequences(){
  var c=document.getElementById('content');
  F('/api/sequences').then(function(d){
    var seqs=d&&d.sequences||[];
    var h='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px"><h3 style="font-size:14px;font-weight:600">PPV Ladders</h3><button class="btn" onclick="newSequence()">+ New Sequence</button></div>';
    if(!seqs.length){h+='<div class="empty"><div class="ico">&#128196;</div><p>No sequences yet</p></div>';c.innerHTML=h;return}
    h+='<div class="panel"><table><thead><tr><th>Name</th><th>Trigger</th><th>Steps</th><th>Total</th><th>Active</th><th></th></tr></thead><tbody>';
    seqs.forEach(function(s){h+='<tr class="clickable" onclick="editSeq('+s.id+')"><td style="color:var(--tx)">'+esc(s.name)+'</td><td><span class="badge '+(s.trigger=='whale'?'whale':s.trigger=='re_engage'?'bad':'avg')+'\">'+s.trigger+'</span></td><td>'+s.step_count+'</td><td>$'+s.total_price.toFixed(0)+'</td><td>'+(s.is_active?'<span style="color:var(--green)">&#9679;</span>':'<span style="color:var(--tx3)">&#9679;</span>')+'</td><td><button class="btn-ghost" onclick="event.stopPropagation();deleteSeq('+s.id+')">&#128465;</button></td></tr>'});
    h+='</tbody></table></div>';c.innerHTML=h;
  });
}
var editSeqId=null;
function newSequence(){editSeqId=null;openSeqEditor({name:'',trigger:'welcome',funnel_stage:'rapport',is_active:true,steps:[]})}
function editSeq(id){
  F('/api/sequences/'+id).then(function(d){
    if(!d)return;editSeqId=d.id;openSeqEditor(d);
  });
}
function openSeqEditor(s){
  var c=document.getElementById('content');
  var triggers=['new_sub','welcome','rapport','whale','re_engage','manual'];
  var h='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px"><h3 style="font-size:14px;font-weight:600">'+(editSeqId?'Edit':'New')+' Sequence</h3><div><button class="btn-ghost" onclick="loadSequences()" style="margin-right:8px">&#8592; Back</button><button class="btn" onclick="saveSeq()">&#128190; Save</button></div></div>';
  h+='<div class="panel" style="padding:18px;margin-bottom:14px"><div class="g3" style="margin-bottom:12px">';
  h+='<div><label>Name</label><input id="sname" value="'+esc(s.name||'')+'" placeholder="e.g. Welcome Ladder"/></div>';
  h+='<div><label>Trigger</label><select id="strigger">'+triggers.map(function(t){return'<option value="'+t+'"'+(s.trigger==t?' selected':'')+'>'+t.replace('_',' ')+'</option>'}).join('')+'</select></div>';
  h+='<div><label>Funnel Stage</label><select id="sfunnel"><option value="rapport"'+(s.funnel_stage=='rapport'?' selected':'')+'>Rapport</option><option value="tease"'+(s.funnel_stage=='tease'?' selected':'')+'>Tease</option><option value="offer"'+(s.funnel_stage=='offer'?' selected':'')+'>Offer</option><option value="close"'+(s.funnel_stage=='close'?' selected':'')+'>Close</option></select></div>';
  h+='<div><label>Active</label><select id="sactive"><option value="1"'+(s.is_active?' selected':'')+'>Yes</option><option value="0"'+(s.is_active?'':' selected')+'>No</option></select></div>';
  h+='</div></div>';
  h+='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px"><h4 style="font-size:12px;font-weight:500;color:var(--tx2)">Steps ('+((s.steps||[]).length)+')</h4><button class="btn-ghost" onclick="addStep()">+ Add Step</button></div>';
  h+='<div id="steps-container"></div>';
  c.innerHTML=h;
  F('/api/vault-albums').then(function(d){
    window.__albums=d&&d.albums||[];
    if(typeof renderSteps=='function')renderSteps(s.steps||[]);
    else setTimeout(function(){renderSteps(s.steps||[])},100);
  });
}
function renderSteps(steps){
  var el=document.getElementById('steps-container');if(!el)return;
  window.__steps=steps.map(function(s,i){
    return {position:i+1,media_id:s.media_id||'$',preview_id:s.preview_id||'',price:s.price||0,tease_script:s.tease_script||'',offer_script:s.offer_script||'',id:s.id||null};
  });
  if(!window.__steps.length){el.innerHTML='<div class="empty"><div class="ico">&#128196;</div><p>Add your first PPV step</p></div>';return}
  var h='';
  window.__steps.forEach(function(step,i){
    h+='<div class="panel" style="padding:14px;margin-bottom:8px;border-left:3px solid var(--accent)">';
    h+='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px"><span style="font-size:11px;font-weight:500;color:var(--accent)">PPV '+(i+1)+'</span><button class="btn-ghost" onclick="removeStep('+i+')" style="padding:2px 8px;font-size:10px">&#128465; Remove</button></div>';
    h+='<div class="g3" style="margin-bottom:8px">';
    h+='<div><label>Media ID</label><div class="row" style="margin-bottom:0"><input id="smedia_'+i+'" value="'+esc(step.media_id||'$')+'" style="flex:1;margin-bottom:0"/><button class="btn-ghost" onclick="pickMedia('+i+')">Browse</button></div></div>';
    h+='<div><label>Preview ID</label><input id="sprev_'+i+'" value="'+esc(step.preview_id||'')+'\"/></div>';
    h+='<div><label>Price ($)</label><input id="sprice_'+i+'" value="'+step.price.toFixed(2)+'"/></div></div>';
    h+='<div class="g3"><div><label>Tease Script</label><textarea id="stease_'+i+'" rows="2">'+esc(step.tease_script||'')+'</textarea></div>';
    h+='<div><label>Offer Script</label><textarea id="soffer_'+i+'" rows="2">'+esc(step.offer_script||'')+'</textarea></div></div></div>';
  });
  el.innerHTML=h;
}
function addStep(){var s=window.__steps||[];s.push({media_id:'$',preview_id:'',price:0,tease_script:'',offer_script:''});renderSteps(s)}
function removeStep(idx){var s=window.__steps||[];s.splice(idx,1);renderSteps(s)}
function pickMedia(idx){
  var albums=window.__albums||[];
  if(!albums.length){alert('No vault albums');return}
  var opts=albums.map(function(a){return'<option value="'+a.id+'">'+esc(a.name||'Album '+a.id)+'</option>'}).join('');
  var h='<div class="panel" style="padding:18px;max-height:300px;overflow-y:auto"><h4 style="font-size:12px;font-weight:500;margin-bottom:10px">Select from Vault</h4>';
  h+='<label>Album</label><select id="album-picker" onchange="loadAlbumMedia('+idx+')">'+opts+'</select>';
  h+='<div id="album-media-list" style="margin-top:10px"><p style="font-size:12px;color:var(--tx3)">Select album</p></div></div>';
  var el=document.getElementById('steps-container');
  if(el)el.insertAdjacentHTML('afterbegin',h);
  if(albums.length)loadAlbumMedia(idx);
}
function loadAlbumMedia(idx){
  var sel=document.getElementById('album-picker');if(!sel)return;
  F('/api/vault-albums/'+sel.value+'/media').then(function(d){
    var items=d&&d.media||[];var el=document.getElementById('album-media-list');if(!el)return;
    if(!items.length){el.innerHTML='<p style="font-size:12px;color:var(--tx3)">No media</p>';return}
    var h='<div class="media-grid" style="margin-top:8px">';
    items.forEach(function(m){
      var typeI=m.type=='video'?'&#127916;':m.type=='image'?'&#128444;':'&#128196;';
      h+='<div class="media-card" style="cursor:pointer" onclick="selectMedia('+idx+',\''+esc(m.id||m.mediaId)+'\')">';
      h+='<div class="ico">'+typeI+'</div><div class="name" style="font-size:10px">'+esc(m.label||m.id||m.mediaId||'')+'</div>';
      h+='<div style="font-size:10px;color:var(--accent);margin-top:4px">select</div></div>';
    });
    h+='</div>';el.innerHTML=h;
  });
}
function selectMedia(idx,mid){
  var inp=document.getElementById('smedia_'+idx);if(inp)inp.value=mid;
  var picker=document.querySelector('#steps-container > .panel');
  if(picker&&picker.querySelector('#album-picker'))picker.remove();
}
function saveSeq(){
  var name=document.getElementById('sname').value;
  var trigger=document.getElementById('strigger').value;
  var funnel=document.getElementById('sfunnel').value;
  var active=document.getElementById('sactive').value==='1';
  var steps=window.__steps||[];
  var stepData=steps.map(function(s,i){
    return {position:i+1,media_id:(document.getElementById('smedia_'+i)||{}).value||'',preview_id:(document.getElementById('sprev_'+i)||{}).value||'',price:parseFloat((document.getElementById('sprice_'+i)||{}).value)||0,tease_script:(document.getElementById('stease_'+i)||{}).value||'',offer_script:(document.getElementById('soffer_'+i)||{}).value||''};
  });
  var body={name:name,trigger:trigger,funnel_stage:funnel,is_active:active,steps:stepData};
  var url='/api/sequences'+(editSeqId?'/'+editSeqId:'');
  fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(function(r){
    if(!r.ok){alert('Save failed');return}
    loadSequences();
  });
}
function deleteSeq(id){
  if(!confirm('Delete this sequence?'))return;
  fetch('/api/sequences/'+id,{method:'DELETE'}).then(function(r){if(r.ok)loadSequences()});
}

setInterval(function(){loadFunnel()},60000);
loadFunnel();
setInterval(function(){F('/health').then(function(r){var d=document.getElementById('dot');if(r&&r.status==='ok'){d.className='dot'}else{d.className='dot off'}})},30000);
</script>
</body>
</html>"""

# ─── Backend (unchanged API logic) ────────────────────

def _list_vault(vault_dir):
    files = []; p = Path(vault_dir)
    if not p.exists(): return files
    for f in sorted(p.iterdir()):
        if f.is_file():
            e = f.suffix.lower()
            ft = "video" if e in (".mp4",".mov",".avi",".mkv",".webm") else "image" if e in (".jpg",".jpeg",".png",".gif",".webp") else "other"
            sz = f.stat().st_size
            if sz > 1024*1024: s = f"{sz/(1024*1024):.1f} MB"
            elif sz > 1024: s = f"{sz/1024:.0f} KB"
            else: s = f"{sz} B"
            files.append({"name":f.name,"type":ft,"size":s})
    return files

def _note(n):
    if n is None: return None
    return {"fan_id":n.fan_id,"display_name":n.display_name,"preferences":n.preferences,"occupation":n.occupation,"total_spent":n.total_spent,"purchase_count":n.purchase_count,"last_purchase_at":n.last_purchase_at.isoformat() if n.last_purchase_at else None,"emotional_triggers":n.emotional_triggers,"hard_limits":n.hard_limits,"facts":n.facts,"notes":n.notes,"relationship_stage":n.relationship_stage,"spend_tier":n.spend_tier}

def _script(s):
    return {"name":s.name,"category":s.category.value if hasattr(s.category,"value") else str(s.category),"description":s.description,"messages":s.messages,"message_count":len(s.messages)}

def _body(h):
    l = int(h.headers.get("Content-Length",0))
    return h.rfile.read(l).decode() if l>0 else ""

class DashboardHandler(BaseHTTPRequestHandler):
    bot = None; vault_dir = "/data/videos"

    def j(self,d,s=200):
        self.send_response(s);self.send_header("Content-Type","application/json");self.send_header("Access-Control-Allow-Origin","*");self.end_headers();self.wfile.write(json.dumps(d,default=str).encode())

    def h(self,html,s=200):
        self.send_response(s);self.send_header("Content-Type","text/html; charset=utf-8");self.end_headers();self.wfile.write(html.encode())

    def do_GET(self):
        p = self.path.split("?")[0]; q = parse_qs(self.path.split("?")[1]) if "?" in self.path else {}
        if p=="/health": return self.j({"status":"ok","service":"fansly-bot","creator":self.bot.creator_id if self.bot else None,"bot_enabled":self.bot.enabled if self.bot else False})
        if p in ("/","/dashboard"): return self.h(DASHBOARD_HTML)
        if p=="/api/conversations": return self._conv()
        if p.startswith("/api/conversations/"): return self._conv_detail(p.rsplit("/",1)[-1])
        if p=="/api/fans": return self._fans()
        if p=="/api/vault": return self.j({"files":_list_vault(self.vault_dir),"dir":self.vault_dir})
        if p=="/api/kpis": return self._kpi()
        if p=="/api/scripts": return self._scrs()
        if p=="/api/connection": return self._conn(q.get("test"))
        if p=="/api/persona": return self._pers_get(q)
        if p=="/api/brand-bible": return self._bible_get()
        if p=="/api/sequences": return self._seq_list()
        if p.startswith("/api/sequences/") and len(p.split("/"))==4: return self._seq_get(p.rsplit("/",1)[-1])
        if p=="/api/vault-albums": return self._vault_albums()
        if p.startswith("/api/vault-albums/") and p.endswith("/media"): return self._vault_album_media(p.split("/")[-2])
        if p.startswith("/api/fan-progress/"): return self._fan_progress(p.rsplit("/",1)[-1])
        if p=="/api/bot/status": return self.j({"enabled":self.bot.enabled if self.bot else False})
        self.j({"error":"not found"},404)

    def do_POST(self):
        p = self.path.split("?")[0]; q = parse_qs(self.path.split("?")[1]) if "?" in self.path else {}; b = _body(self)
        if p=="/api/persona": return self._pers_post(q,b)
        if p=="/api/brand-bible": return self._bible_post(b)
        if p=="/api/sequences": return self._seq_create(b)
        if p.startswith("/api/sequences/") and len(p.split("/"))==4: return self._seq_update(p.rsplit("/",1)[-1], b)
        if p=="/api/bot/toggle": return self._bot_toggle(b)
        self.j({"error":"not found"},404)

    def do_DELETE(self):
        p = self.path.split("?")[0]
        if p.startswith("/api/sequences/") and len(p.split("/"))==4: return self._seq_delete(p.rsplit("/",1)[-1])
        self.j({"error":"not found"},404)

    def _list_notes(self):
        from ..notes.repository import FAN_NOTES_TABLE, _row_to_note
        rows = []
        try:
            with self.bot.note_repo.engine.connect() as c:
                r = c.execute(FAN_NOTES_TABLE.select().where(FAN_NOTES_TABLE.c.creator_id==self.bot.creator_id))
                for row in r:
                    try: rows.append(_row_to_note(row))
                    except: pass
        except: pass
        return rows

    def _conv(self):
        if not self.bot: return self.j({"fans":[]})
        fans = []
        for fid,sess in self.bot.sessions.items():
            n = self.bot.note_repo.get(fid,self.bot.creator_id)
            fans.append({"fan_id":fid,"display_name":n.display_name if n else None,"spend_tier":n.spend_tier if n else "time_waster","funnel_stage":sess.funnel.current_stage.value,"spiral_level":sess.funnel.level.number,"cooldown":sess.funnel.cooldown,"message_count":sess.message_count,"last_activity":sess.last_activity.isoformat() if sess.last_activity else None,"fact_count":len(n.facts) if n else 0})
        fans.sort(key=lambda f:f.get("last_activity")or"",reverse=True)
        return self.j({"fans":fans})

    def _conv_detail(self, fan_id):
        """Full memory view for one fan: profile, remembered facts, message history."""
        if not self.bot: return self.j({"error": "bot not initialized"}, 503)
        note = self.bot.note_repo.get(fan_id, self.bot.creator_id)
        history = []
        if self.bot.message_store:
            history = self.bot.message_store.get_history(fan_id, self.bot.creator_id, limit=100)
        sess = self.bot.sessions.get(fan_id)
        style = self.bot._style_profiles.get(fan_id)

        # Get PPV sequence progress
        seq_progress = []
        try:
            seq_progress = self.bot.sequence_repo.get_fan_progress(fan_id, self.bot.creator_id)
        except Exception:
            pass
        sequences_data = []
        for p in seq_progress:
            seq = None
            try:
                seq = self.bot.sequence_repo.get_sequence(p.sequence_id)
            except Exception:
                pass
            sequences_data.append({
                "sequence_id": p.sequence_id,
                "sequence_name": seq.name if seq else "unknown",
                "current_step": p.current_step,
                "total_steps": seq.step_count() if seq else 0,
                "status": p.status.value,
                "last_sent_at": str(p.last_sent_at) if p.last_sent_at else None,
                "bought_at": str(p.bought_at) if p.bought_at else None,
            })

        return self.j({
            "fan_id": fan_id,
            "profile": _note(note),
            "facts": note.facts if note else [],
            "preferences": note.preferences if note else [],
            "hard_limits": note.hard_limits if note else [],
            "funnel_stage": sess.funnel.current_stage.value if sess else None,
            "sequences": sequences_data,
            "spiral_level": sess.funnel.level.number if sess else 0,
            "spiral_ppvs_bought": sess.funnel.level.ppvs_bought if sess else 0,
            "cooldown": sess.funnel.cooldown if sess else False,
            "warmup": sess.funnel.is_warmup if sess else False,
            "style": {
                "formality": style.formality if style else "unknown",
                "avg_length": round(style.avg_length, 1) if style else 0,
                "emoji_rate": round(style.emoji_rate, 2) if style else 0,
                "uses_abbreviations": style.uses_abbreviations if style else False,
                "slang": style.slang if style else [],
            },
            "message_count_stored": len(history),
            "messages": history,
        })

    def _fans(self):
        if not self.bot: return self.j({"fans":[]})
        return self.j({"fans":[_note(n) for n in self._list_notes()]})

    def _kpi(self):
        if not self.bot: return self.j({"error":"bot not initialized"},503)
        ns = self._list_notes(); a = len(self.bot.sessions); ts = sum(n.total_spent for n in ns); pc = sum(n.purchase_count for n in ns)
        k = self.bot.kpi.summary({"subscription_revenue":ts,"dm_revenue":ts,"unlocks":pc,"sends":max(pc*3,1),"total_dm_revenue":ts,"purchase_count":pc,"response_times":[],"completed_scripts":0,"started_scripts":0,"aftercare_count":0,"return_purchase_count":0})
        k["active_fans"]=a; return self.j(k)

    def _scrs(self):
        if not self.bot: return self.j({"scripts":[]})
        return self.j({"scripts":[_script(s) for s in getattr(self.bot.script_library,"templates",[])]})

    def _conn(self,test):
        if not self.bot: return self.j({"connected":False,"account_id":""})
        ok=False;err=None
        if test:
            try: self.bot.client.list_chats(filter_type="all",sort="newest");ok=True
            except Exception as e: err=str(e)[:200]
        else: ok=True
        return self.j({"connected":ok,"account_id":(self.bot.account_id[:8]+"..." if self.bot.account_id else ""),"error":err})

    def _pers_get(self,q):
        cid = (q.get("creator",[None])or[None])[0] or (self.bot.creator_id if self.bot else "sunny_charm")
        p = Path(PERSONA_DIR)/f"{cid}.yaml"
        return self.j({"creator_id":cid,"yaml":p.read_text() if p.exists() else ""})

    def _pers_post(self,q,b):
        cid = (q.get("creator",[None])or[None])[0] or (self.bot.creator_id if self.bot else "sunny_charm")
        try: yaml.safe_load(b)
        except yaml.YAMLError as e: return self.j({"error":str(e)},400)
        p = Path(PERSONA_DIR); p.mkdir(parents=True,exist_ok=True); (p/f"{cid}.yaml").write_text(b)
        return self.j({"status":"ok"})

    def _bible_get(self):
        p = Path(BRAND_BIBLE_PATH)
        return self.j({"content":p.read_text() if p.exists() else "","path":str(p)})

    def _bible_post(self,b):
        p = Path(BRAND_BIBLE_PATH); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(b)
        return self.j({"status":"ok"})

    # ─── PPV SEQUENCES ──────────────────────────────────

    def _seq_list(self):
        if not self.bot: return self.j({"sequences":[]})
        try:
            seqs = self.bot.sequence_repo.list_sequences()
            return self.j({"sequences":[
                {"id":s.id,"name":s.name,"trigger":s.trigger.value,"funnel_stage":s.funnel_stage,
                 "is_active":s.is_active,"step_count":s.step_count(),"total_price":round(s.total_price(),2),
                 "created_at":str(s.created_at)}
                for s in seqs
            ]})
        except Exception as e:
            return self.j({"error":str(e)},500)

    def _seq_get(self, seq_id_str):
        if not self.bot: return self.j({"error":"no bot"},503)
        try:
            s = self.bot.sequence_repo.get_sequence(int(seq_id_str))
            if not s: return self.j({"error":"not found"},404)
            return self.j({
                "id":s.id,"name":s.name,"trigger":s.trigger.value,"funnel_stage":s.funnel_stage,
                "is_active":s.is_active,"step_count":s.step_count(),"total_price":round(s.total_price(),2),
                "created_at":str(s.created_at),
                "steps":[{"id":st.id,"position":st.position,"media_id":st.media_id,"preview_id":st.preview_id,
                          "price":st.price,"tease_script":st.tease_script,"offer_script":st.offer_script}
                         for st in s.steps]
            })
        except Exception as e:
            return self.j({"error":str(e)},500)

    def _seq_create(self, body):
        if not self.bot: return self.j({"error":"no bot"},503)
        try:
            data = json.loads(body)
            s = Sequence(
                name=data["name"],
                trigger=SequenceTrigger(data.get("trigger","welcome")),
                funnel_stage=data.get("funnel_stage","rapport"),
                is_active=data.get("is_active",True),
            )
            saved = self.bot.sequence_repo.save_sequence(s)
            if "steps" in data:
                for step_data in data["steps"]:
                    step = SequenceStep(
                        sequence_id=saved.id,
                        position=step_data.get("position",1),
                        media_id=step_data.get("media_id",""),
                        preview_id=step_data.get("preview_id"),
                        price=float(step_data.get("price",0)),
                        tease_script=step_data.get("tease_script",""),
                        offer_script=step_data.get("offer_script",""),
                    )
                    self.bot.sequence_repo.save_step(step)
            return self.j({"status":"ok","id":saved.id})
        except Exception as e:
            return self.j({"error":str(e)},500)

    def _seq_update(self, seq_id_str, body):
        if not self.bot: return self.j({"error":"no bot"},503)
        try:
            data = json.loads(body)
            s = self.bot.sequence_repo.get_sequence(int(seq_id_str))
            if not s: return self.j({"error":"not found"},404)
            s.name = data.get("name",s.name)
            s.trigger = SequenceTrigger(data.get("trigger",s.trigger.value))
            s.funnel_stage = data.get("funnel_stage",s.funnel_stage)
            s.is_active = data.get("is_active",s.is_active)
            self.bot.sequence_repo.save_sequence(s)
            for st in self.bot.sequence_repo.get_steps(s.id):
                self.bot.sequence_repo.delete_step(st.id)
            for step_data in data.get("steps",[]):
                step = SequenceStep(
                    sequence_id=s.id,
                    position=step_data.get("position",1),
                    media_id=step_data.get("media_id",""),
                    preview_id=step_data.get("preview_id"),
                    price=float(step_data.get("price",0)),
                    tease_script=step_data.get("tease_script",""),
                    offer_script=step_data.get("offer_script",""),
                )
                self.bot.sequence_repo.save_step(step)
            return self.j({"status":"ok"})
        except Exception as e:
            return self.j({"error":str(e)},500)

    def _seq_delete(self, seq_id_str):
        if not self.bot: return self.j({"error":"no bot"},503)
        try:
            self.bot.sequence_repo.delete_sequence(int(seq_id_str))
            return self.j({"status":"ok"})
        except Exception as e:
            return self.j({"error":str(e)},500)

    # ─── VAULT ALBUMS (Fansly API) ─────────────────────

    def _vault_albums(self):
        if not self.bot: return self.j({"albums":[]})
        try:
            albums = self.bot.client.list_albums()
            return self.j({"albums":[
                {"id":a.get("id") or a.get("albumId"),"name":a.get("name") or a.get("label","Album")}
                for a in albums
            ]})
        except Exception as e:
            return self.j({"error":str(e),"albums":[]})

    def _vault_album_media(self, album_id):
        if not self.bot: return self.j({"media":[]})
        try:
            media, _ = self.bot.client.get_album_media(album_id)
            if isinstance(media,list):
                return self.j({"media":[
                    {"id":m.get("id") or m.get("mediaId"),"mediaId":m.get("mediaId"),
                     "type":m.get("type","unknown"),"label":m.get("label") or m.get("description",""),
                     "previewId":m.get("previewId")}
                    for m in media
                ]})
            return self.j({"media":[]})
        except Exception as e:
            return self.j({"error":str(e),"media":[]})

    # ─── FAN PROGRESS ──────────────────────────────────

    def _fan_progress(self, fan_id):
        if not self.bot: return self.j({"progress":[]})
        try:
            progress_list = self.bot.sequence_repo.get_fan_progress(fan_id, self.bot.creator_id)
            result = []
            for p in progress_list:
                seq = self.bot.sequence_repo.get_sequence(p.sequence_id)
                result.append({
                    "fan_id":p.fan_id,
                    "sequence_id":p.sequence_id,
                    "sequence_name":seq.name if seq else "unknown",
                    "current_step":p.current_step,
                    "total_steps":seq.step_count() if seq else 0,
                    "status":p.status.value,
                    "last_sent_at":str(p.last_sent_at) if p.last_sent_at else None,
                    "bought_at":str(p.bought_at) if p.bought_at else None,
                })
            return self.j({"progress":result,"fan_id":fan_id})
        except Exception as e:
            return self.j({"error":str(e),"progress":[]})

    # ─── BOT TOGGLE ────────────────────────────────────

    def _bot_toggle(self, body: str):
        """Toggle bot on/off and persist to DB."""
        if not self.bot:
            return self.j({"error": "bot not initialized"}, 503)
        try:
            data = json.loads(body) if body else {}
            force = data.get("enabled") if "enabled" in data else None
            new_state = self.bot.toggle(force=force)
            # Persist to DB
            from ..settings.store import SettingsStore
            store = SettingsStore(
                db_url=self.bot.note_repo.engine.url.render_as_string(hide_password=False)
                if hasattr(self.bot.note_repo.engine.url, 'render_as_string')
                else str(self.bot.note_repo.engine.url)
            )
            store.create_table()
            store.set("bot_enabled", str(new_state).lower())
            return self.j({"enabled": new_state})
        except Exception as e:
            return self.j({"error": str(e)}, 500)

    def log_message(self,*a): pass

class DashboardServer:
    def __init__(self,bot,port=8080,vault_dir="/data/videos"):
        DashboardHandler.bot = bot; DashboardHandler.vault_dir = vault_dir
        self.server = HTTPServer(("0.0.0.0",port),DashboardHandler)
    def handle_request(self): self.server.handle_request()
    def shutdown(self): self.server.shutdown()