"""
Dashboard web server — SPA + REST API for the Fansly AI bot.
Sidebar navigation, Linear-dark aesthetic, proper UX hierarchy per section.
"""
import base64
import binascii
import hmac
import json
import logging
import math
import os
import re
import secrets
from datetime import datetime, timezone

import yaml
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Optional, TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import text

from ..persistence.dashboard import DashboardReadRepository
from ..persistence.crm import CrmSyncRepository
from ..persistence.pipeline import MessageProcessingRepository
from ..persistence.presence import PresenceRepository
from ..media.repository import MediaAsset, MediaAssetRepository
from ..persona.models import PersonaDocument
from ..scripts.loader import BUILTIN_SCRIPTS
from ..scripts.models import ScriptCategory, ScriptTemplate, ScriptVariable
from ..scripts.repository import ScriptTemplateRepository
from ..sequences.models import Sequence, SequenceTrigger, SequenceStep, FanSequenceProgress, StepStatus
from ..settings.chat_guidance import ChatGuidanceError

logger = logging.getLogger("fansly-bot.dashboard")
if TYPE_CHECKING:
    from ..bot import FanslyBot

PERSONA_DIR = "/data/config/creators"
BRAND_BIBLE_PATH = "/data/config/brand_bible.md"
MAX_BODY_BYTES = 1024 * 1024
CREATOR_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
PROVIDER_MEDIA_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
)
SCRIPT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


class PayloadTooLargeError(ValueError):
    """Raised before reading a request body that exceeds the dashboard limit."""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Sunny Charm</title>
<style nonce="__CSP_NONCE__">
:root{
  color-scheme:light;
  --bg:#f5f5f7;
  --panel:rgba(255,255,255,.82);
  --surf:#fff;
  --surf2:#f9f9fb;
  --hover:rgba(0,0,0,.035);
  --tx:#1d1d1f;
  --tx2:#515154;
  --tx3:#86868b;
  --accent:#0071e3;
  --ahover:#0077ed;
  --abg:rgba(0,113,227,.09);
  --border:rgba(0,0,0,.09);
  --bsub:rgba(0,0,0,.055);
  --green:#248a3d;
  --red:#d70015;
  --amber:#b25000;
  --shadow:0 1px 2px rgba(0,0,0,.04),0 10px 30px rgba(0,0,0,.035);
  --radius:18px
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{background:var(--bg)}
body{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",sans-serif;background:var(--bg);color:var(--tx);-webkit-font-smoothing:antialiased;height:100vh;height:100dvh;overflow:hidden;display:flex}
button,input,textarea,select{font:inherit}
button:focus-visible,a:focus-visible,input:focus-visible,textarea:focus-visible,select:focus-visible{outline:3px solid rgba(0,113,227,.28);outline-offset:2px}
/* SIDEBAR */
.sidebar{width:248px;min-width:248px;background:var(--panel);border-right:1px solid var(--bsub);display:flex;flex-direction:column;padding:18px 14px 14px;backdrop-filter:saturate(180%) blur(20px);-webkit-backdrop-filter:saturate(180%) blur(20px)}
.brand{height:52px;display:flex;align-items:center;padding:0 10px;gap:11px;margin-bottom:20px}
.brand-mark{width:34px;height:34px;border-radius:10px;background:linear-gradient(145deg,#78c3ff,#0069d9);box-shadow:inset 0 1px rgba(255,255,255,.55),0 7px 18px rgba(0,113,227,.2);display:grid;place-items:center;color:#fff;font-size:15px;font-weight:700}
.brand-copy{min-width:0}
.brand-name{font-size:14px;font-weight:650;letter-spacing:-.18px;white-space:nowrap}
.brand-kicker{font-size:11px;color:var(--tx3);margin-top:2px}
.sidebar nav{flex:1;display:flex;flex-direction:column;gap:4px}
.nav-item{appearance:none;width:100%;border:0;background:transparent;display:flex;align-items:center;gap:12px;min-height:44px;padding:0 12px;border-radius:12px;font-size:13px;font-weight:520;color:var(--tx2);cursor:pointer;transition:background .16s,color .16s,transform .16s;text-align:left}
.nav-item:hover{color:var(--tx);background:var(--hover)}
.nav-item:active{transform:scale(.98)}
.nav-item.active{color:var(--accent);background:var(--abg);font-weight:600}
.nav-item svg{width:19px;height:19px;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;flex:none}
.sidebar .footer{padding:12px 10px 2px;border-top:1px solid var(--bsub)}
.sidebar .footer a{color:var(--tx3);text-decoration:none;display:flex;align-items:center;justify-content:space-between;min-height:38px;font-size:12px}
.sidebar .footer a:hover{color:var(--accent)}
/* MAIN */
main{min-width:0;flex:1;display:flex;flex-direction:column;overflow:hidden}
.topbar{min-height:76px;background:rgba(245,245,247,.82);border-bottom:1px solid var(--bsub);display:flex;align-items:center;padding:12px 32px;justify-content:space-between;gap:18px;backdrop-filter:saturate(180%) blur(18px);-webkit-backdrop-filter:saturate(180%) blur(18px);z-index:10}
.page-heading{min-width:0}
.topbar h1{font-size:22px;line-height:1.15;font-weight:680;letter-spacing:-.45px}
.topbar .meta{display:block;font-size:12px;line-height:1.35;color:var(--tx3);margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.status-group{display:flex;align-items:center;gap:8px;flex:none}
.health-link{display:inline-flex;align-items:center;gap:6px;color:var(--tx2);text-decoration:none;font-size:12px;font-weight:550;min-height:40px;padding:0 12px;border-radius:999px}
.health-link:hover{background:var(--hover);color:var(--tx)}
.health-link::before{content:'';width:7px;height:7px;border-radius:50%;background:var(--green)}
.toggle-pill{appearance:none;display:inline-flex;align-items:center;gap:8px;min-height:40px;padding:0 14px;border-radius:999px;cursor:pointer;transition:background .15s,transform .15s;border:1px solid var(--border);background:var(--surf);font-size:12px;font-weight:600;color:var(--tx);box-shadow:0 1px 2px rgba(0,0,0,.03);user-select:none}
.toggle-pill:hover{background:var(--surf2)}
.toggle-pill:active{transform:scale(.97)}
.toggle-pill .dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 0 4px rgba(36,138,61,.1)}
.toggle-pill .dot.off{background:var(--red);box-shadow:0 0 0 4px rgba(215,0,21,.08)}
.toggle-pill #toggle-label{font-size:12px;color:var(--green)}
.content{flex:1;overflow-y:auto;padding:30px 32px 56px;scrollbar-gutter:stable}
.content>*{width:min(1240px,100%);margin-left:auto;margin-right:auto}
.section-intro{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin-bottom:18px}
.section-intro h2{font-size:17px;font-weight:650;letter-spacing:-.25px}
.section-intro p{font-size:12px;line-height:1.45;color:var(--tx3);margin-top:4px}
/* CARDS & GRIDS */
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}
.card{background:var(--surf);border:1px solid var(--border);border-radius:var(--radius);padding:20px;box-shadow:var(--shadow)}
.card h3{font-size:11px;font-weight:560;color:var(--tx3);letter-spacing:.1px;margin-bottom:9px}
.card .v{font-size:25px;font-weight:680;font-variant-numeric:tabular-nums;letter-spacing:-.55px}
.v.up{color:var(--green)}.v.warn{color:var(--amber)}.v.bad{color:var(--red)}
/* TABLE */
.panel{background:var(--surf);border:1px solid var(--border);border-radius:var(--radius);overflow:auto;box-shadow:var(--shadow)}
.panel table{width:100%;border-collapse:collapse}
.panel th{text-align:left;padding:12px 16px;font-size:10px;font-weight:600;color:var(--tx3);text-transform:uppercase;letter-spacing:.55px;border-bottom:1px solid var(--border);background:var(--surf2);white-space:nowrap}
.panel td{padding:13px 16px;font-size:12px;color:var(--tx2);border-bottom:1px solid var(--bsub);font-variant-numeric:tabular-nums;white-space:nowrap}
.panel tr:hover td{background:var(--hover)}
.panel tr:last-child td{border-bottom:none}
/* BADGE */
.badge{display:inline-flex;align-items:center;gap:5px;padding:3px 8px;border-radius:9999px;font-size:10px;font-weight:600}
.badge::before{content:'';width:5px;height:5px;border-radius:50%;flex-shrink:0}
.badge.whale{background:var(--abg);color:var(--accent)}.badge.whale::before{background:var(--accent)}
.badge.avg{background:rgba(36,138,61,.1);color:var(--green)}.badge.avg::before{background:var(--green)}
.badge.low{background:var(--hover);color:var(--tx3)}.badge.low::before{background:var(--tx3)}
.badge.rapport{background:rgba(0,113,227,.08);color:#0068d0}.badge.rapport::before{background:#0071e3}
.badge.tease{background:rgba(175,82,222,.08);color:#8944ab}.badge.tease::before{background:#af52de}
.badge.offer{background:rgba(215,0,21,.07);color:var(--red)}.badge.offer::before{background:var(--red)}
.badge.handle{background:rgba(178,80,0,.08);color:var(--amber)}.badge.handle::before{background:var(--amber)}
.badge.close{background:rgba(36,138,61,.1);color:var(--green)}.badge.close::before{background:var(--green)}
/* VAULT */
.media-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:14px}
.media-card{background:var(--surf);border:1px solid var(--border);border-radius:var(--radius);padding:22px 14px;text-align:center;transition:background .15s,transform .15s;cursor:default;box-shadow:var(--shadow)}
.media-card:hover{background:var(--hover)}
.media-card .ico{font-size:24px;margin-bottom:10px;filter:grayscale(.35)}
.media-card .name{font-size:12px;color:var(--tx2);word-break:break-word;line-height:1.35}
.media-card .size{font-size:10px;color:var(--tx3);margin-top:5px}
/* EMPTY */
.empty{min-height:360px;padding:64px 24px;text-align:center;color:var(--tx3);background:var(--surf);border:1px solid var(--border);border-radius:24px;box-shadow:var(--shadow);display:flex;flex-direction:column;align-items:center;justify-content:center}
.empty .ico{width:52px;height:52px;display:grid;place-items:center;border-radius:16px;background:var(--surf2);border:1px solid var(--border);font-size:22px;margin-bottom:18px;filter:grayscale(1);opacity:.78}
.empty h3{font-size:17px;color:var(--tx);font-weight:650;letter-spacing:-.2px;margin-bottom:7px}
.empty p{font-size:13px;line-height:1.5;max-width:390px}
/* SCRIPTS */
.cat{margin-bottom:22px}
.cat h4{font-size:11px;font-weight:650;color:var(--tx3);text-transform:uppercase;letter-spacing:.55px;margin:0 0 9px 4px}
/* SETTINGS */
.block{margin-bottom:18px;background:var(--surf);border:1px solid var(--border);border-radius:var(--radius);padding:22px;box-shadow:var(--shadow)}
.block h3{font-size:16px;font-weight:650;margin-bottom:14px;letter-spacing:-.2px}
label{display:block;font-size:11px;font-weight:600;color:var(--tx3);margin-bottom:6px}
input,textarea,select{width:100%;background:var(--surf2);border:1px solid var(--border);border-radius:11px;padding:10px 12px;color:var(--tx);font-family:"SF Mono","Cascadia Code",Consolas,monospace;font-size:12px;resize:vertical;transition:border .15s,box-shadow .15s}
input:focus,textarea:focus,select:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(0,113,227,.1);outline:none}
textarea{min-height:200px;line-height:1.5}
select{font-family:inherit;font-size:13px}
.btn{background:var(--accent);color:#fff;border:none;border-radius:999px;min-height:40px;padding:0 18px;font-size:12px;font-weight:600;cursor:pointer;transition:background .15s,transform .1s;box-shadow:0 4px 12px rgba(0,113,227,.17)}
.btn:hover{background:var(--ahover)}.btn:active{transform:scale(.96)}
.btn-ghost{background:var(--surf);color:var(--tx2);border:1px solid var(--border);border-radius:999px;min-height:36px;padding:0 14px;font-size:11px;font-weight:600;cursor:pointer;transition:all .15s}
.btn-ghost:hover{color:var(--tx);background:var(--surf2);border-color:rgba(0,0,0,.14)}
.row{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.done{color:var(--green);font-size:11px;font-weight:500;display:none;align-items:center;gap:4px}
.done::before{content:'\2713 '}
#conn-result{font-size:11px;font-weight:500}
.g3{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
/* FAN DETAIL DRAWER */
.drawer{position:fixed;top:0;right:-540px;width:540px;max-width:94vw;height:100vh;height:100dvh;background:rgba(255,255,255,.96);border-left:1px solid var(--border);z-index:50;transition:right .24s cubic-bezier(.32,.72,0,1);display:flex;flex-direction:column;box-shadow:-18px 0 50px rgba(0,0,0,.08);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px)}
.drawer.open{right:0}
.drawer .dhead{padding:18px 22px;border-bottom:1px solid var(--bsub);display:flex;align-items:center;justify-content:space-between}
.drawer .dhead h3{font-size:17px;font-weight:650;letter-spacing:-.2px}
.drawer .dclose{width:34px;height:34px;border-radius:50%;background:var(--surf2);border:0;color:var(--tx2);font-size:20px;cursor:pointer}
.drawer .dclose:hover{color:var(--tx)}
.drawer .dbody{flex:1;overflow-y:auto;padding:22px}
.dsec{margin-bottom:24px}
.dsec h4{font-size:10px;font-weight:650;color:var(--tx3);text-transform:uppercase;letter-spacing:.55px;margin-bottom:9px}
.fact-list{list-style:none}
.fact-list li{font-size:12px;color:var(--tx2);padding:9px 11px;background:var(--surf2);border:1px solid var(--bsub);border-radius:10px;margin-bottom:7px}
.fact-list li::before{content:'\U0001f9e0 ';font-size:11px}
.msg{display:flex;margin-bottom:10px}
.msg .bubble{max-width:85%;padding:9px 13px;border-radius:16px;font-size:12px;line-height:1.45}
.msg.fan .bubble{background:var(--surf2);border:1px solid var(--bsub);color:var(--tx2)}
.msg.creator{justify-content:flex-end}
.msg.creator .bubble{background:var(--accent);color:#fff}
.msg .who{font-size:9px;color:var(--tx3);margin-top:2px}
.msgwrap{display:flex;flex-direction:column}
.msg.fan .msgwrap{align-items:flex-start}
.msg.creator .msgwrap{align-items:flex-end}
.pill-row{display:flex;flex-wrap:wrap;gap:6px}
.pill{font-size:11px;padding:4px 10px;border-radius:9999px;background:var(--surf2);border:1px solid var(--bsub);color:var(--tx2)}
tr.clickable{cursor:pointer}
tr.clickable:hover td{background:var(--hover)}
@media(max-width:900px){
  .sidebar{width:220px;min-width:220px}
  .content{padding-left:22px;padding-right:22px}
  .topbar{padding-left:22px;padding-right:22px}
}
@media(max-width:720px){
  body{display:block}
  .sidebar{position:fixed;z-index:40;left:0;right:0;top:auto;bottom:0;width:100%;min-width:0;height:76px;padding:5px 6px max(6px,env(safe-area-inset-bottom));border-right:0;border-top:1px solid var(--border);background:rgba(250,250,252,.92)}
  .brand,.sidebar .footer{display:none}
  .sidebar nav{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:0}
  .nav-item{min-height:58px;padding:5px 2px;border-radius:10px;flex-direction:column;justify-content:center;gap:3px;font-size:9px;text-align:center;white-space:nowrap}
  .nav-item svg{width:19px;height:19px}
  main{height:calc(100vh - 76px);height:calc(100dvh - 76px)}
  .topbar{min-height:70px;padding:10px 16px}
  .topbar h1{font-size:20px}
  .topbar .meta{font-size:11px;max-width:180px}
  .health-link{display:none}
  .toggle-pill{min-height:38px;padding:0 12px}
  .content{padding:20px 14px 36px;scrollbar-gutter:auto}
  .section-intro{align-items:flex-start;flex-direction:column}
  .cards{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
  .card{border-radius:15px;padding:16px}
  .card .v{font-size:21px}
  .panel{border-radius:16px}
  .empty{min-height:310px;border-radius:20px;padding:44px 22px}
  .block{border-radius:16px;padding:18px}
  .row{align-items:stretch;flex-wrap:wrap}
  .row select,.row input{flex:1 1 180px}
  .drawer{width:100%;max-width:100%}
}
@media(max-width:390px){
  .nav-item{font-size:8px}
  .cards{grid-template-columns:1fr}
}
@media(prefers-reduced-motion:reduce){
  *,*::before,*::after{scroll-behavior:auto!important;transition-duration:.01ms!important;animation-duration:.01ms!important;animation-iteration-count:1!important}
}
</style>
</head>
<body>
<aside class="sidebar">
<div class="brand"><div class="brand-mark" aria-hidden="true">S</div><div class="brand-copy"><div class="brand-name">Sunny Charm</div><div class="brand-kicker">Creator console</div></div></div>
<nav aria-label="Primary">
<button type="button" class="nav-item active" data-tab="funnel" aria-current="page"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16M6 10h12M9 15h6M11 20h2"/></svg><span>Funnel</span></button>
<button type="button" class="nav-item" data-tab="vault"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 7.5h6l2-2h9v13h-17z"/></svg><span>Vault</span></button>
<button type="button" class="nav-item" data-tab="fans"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="8" r="3"/><path d="M3.5 19c.4-3.8 2.2-5.7 5.5-5.7s5.1 1.9 5.5 5.7M15.5 5.6a3 3 0 0 1 0 5.7M16.8 14c2.2.5 3.4 2.2 3.7 5"/></svg><span>Fans</span></button>
<button type="button" class="nav-item" data-tab="scripts"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.5h9l3 3V20.5H6zM9 10h6M9 14h6M9 18h4"/></svg><span>Scripts</span></button>
<button type="button" class="nav-item" data-tab="kpis"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 19V11M12 19V5M19 19v-7"/></svg><span>KPIs</span></button>
<button type="button" class="nav-item" data-tab="sequences"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="6" cy="6" r="2"/><circle cx="18" cy="12" r="2"/><circle cx="6" cy="18" r="2"/><path d="M8 6h3a3 3 0 0 1 3 3v0a3 3 0 0 0 3 3M8 18h3a3 3 0 0 0 3-3v0a3 3 0 0 1 3-3"/></svg><span>Flows</span></button>
<button type="button" class="nav-item" data-tab="settings"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1a8 8 0 0 0-1.8-1L14.4 3h-4.8l-.4 3.1a8 8 0 0 0-1.8 1L5 6.1 3 9.5 5.1 11a7 7 0 0 0 0 2L3 14.5 5 18l2.4-1a8 8 0 0 0 1.8 1l.4 3h4.8l.4-3a8 8 0 0 0 1.8-1l2.4 1 2-3.5-2.1-1.5a7 7 0 0 0 .1-1z"/></svg><span>Settings</span></button>
</nav>
<div class="footer"><a href="/health" target="_blank" rel="noopener">API health <span aria-hidden="true">&#8599;</span></a></div>
</aside>
<main>
<header class="topbar"><div class="page-heading"><h1 id="page-title">Funnel</h1><span class="meta" id="page-meta">Live conversations and buying stages</span></div><div class="status-group"><a class="health-link" href="/health" target="_blank" rel="noopener">Service healthy</a><button type="button" class="toggle-pill" id="bot-toggle" data-action="toggle-bot" aria-label="Toggle bot"><span class="dot" id="dot"></span><span id="toggle-label">ON</span></button></div></header>
<div class="content" id="content"></div>
</main>
<div class="drawer" id="drawer">
<div class="dhead"><h3 id="dtitle">Fan</h3><button type="button" class="dclose" data-action="close-drawer" aria-label="Close details">&times;</button></div>
<div class="dbody" id="dbody"></div>
</div>
<script nonce="__CSP_NONCE__">
const CSRF_TOKEN=__CSRF_TOKEN__;
function navTo(tab){
  document.querySelectorAll('.nav-item').forEach(function(item){item.classList.remove('active');item.removeAttribute('aria-current')});
  var selected=document.querySelector('.nav-item[data-tab="'+tab+'"]');
  if(selected){selected.classList.add('active');selected.setAttribute('aria-current','page')}
  var titles={'funnel':'Funnel','vault':'Vault','fans':'Fans','scripts':'Scripts','kpis':'KPIs','sequences':'PPV Sequences','settings':'Settings'};
  var subtitles={'funnel':'Live conversations and buying stages','vault':'Local storage and provider readiness','fans':'Audience memory and attributed value','scripts':'Reusable conversation playbooks','kpis':'Durable attributed events only','sequences':'Drafts and provider delivery capability','settings':'Connections and runtime configuration'};
  document.getElementById('page-title').textContent=titles[tab]||tab;
  document.getElementById('page-meta').textContent=subtitles[tab]||'';
  document.getElementById('content').scrollTop=0;
  if(tab==='funnel')loadFunnel();if(tab==='vault')loadVault();if(tab==='fans')loadFans();
  if(tab==='scripts')loadScripts();if(tab==='kpis')loadKPIs();if(tab==='sequences')loadSequences();if(tab==='settings')loadSettings();
}
async function F(u){try{var r=await fetch(u,{credentials:'same-origin',cache:'no-store'});if(!r.ok)return null;return await r.json()}catch(e){return null}}
async function M(u,options){
  options=options||{};
  options.credentials='same-origin';
  options.cache='no-store';
  options.headers=Object.assign({},options.headers||{}, {'X-CSRF-Token':CSRF_TOKEN});
  return fetch(u,options);
}
function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function attr(s){return esc(s).replace(/"/g,'&quot;').replace(/'/g,'&#39;')}
function B(c,t){var allowed=['whale','avg','low','rapport','tease','offer','handle','close','bad'];c=allowed.indexOf(c)>=0?c:'low';return'<span class="badge '+c+'">'+esc(t)+'</span>'}
function ft(t){if(!t)return'\u2014';var d=new Date(t+'Z'),n=new Date(),s=Math.floor((n-d)/1000);if(s<60)return s+'s';if(s<3600)return Math.floor(s/60)+'m';return Math.floor(s/3600)+'h'}
function emptyState(icon,title,description){return'<div class="empty"><div class="ico" aria-hidden="true">'+icon+'</div><h3>'+title+'</h3><p>'+description+'</p></div>'}
function sectionIntro(title,description,action){return'<div class="section-intro"><div><h2>'+title+'</h2><p>'+description+'</p></div>'+(action||'')+'</div>'}

function loadFunnel(){
  var c=document.getElementById('content');
  F('/api/conversations').then(function(d){
    if(!d||!d.fans||!d.fans.length){c.innerHTML=emptyState('&#8595;','No conversations yet','New fan messages will appear here automatically, ordered by their position in your sales funnel.');return}
    var h='<div class="panel"><table><thead><tr><th>Fan</th><th>Tier</th><th>Stage</th><th>Level</th><th>Msgs</th><th>Facts</th><th>Active</th></tr></thead><tbody>';
    d.fans.forEach(function(f){var fid=String(f.fan_id||'');h+='<tr class="clickable" data-action="fan-detail" data-fan-id="'+attr(fid)+'"><td style="color:var(--tx)">'+esc(f.display_name||fid.slice(0,10))+'</td><td>'+B(f.spend_tier==='whale'?'whale':f.spend_tier==='average'?'avg':'low',f.spend_tier)+'</td><td>'+B(f.funnel_stage,f.funnel_stage)+(f.cooldown?' <span style="color:var(--tx3);font-size:10px">&#9924;</span>':'')+'</td><td>'+B('avg','L'+(Number(f.spiral_level)||0))+'</td><td>'+Number(f.message_count||0)+'</td><td>'+Number(f.fact_count||0)+'</td><td>'+ft(f.last_activity)+'</td></tr>'});
    h+='</tbody></table></div>';c.innerHTML=h;
  });
}
setInterval(function(){if(document.querySelector('.nav-item[data-tab="funnel"].active')&&!document.getElementById('drawer').classList.contains('open'))loadFunnel()},15000);

function fanDetail(fanId){
  var dr=document.getElementById('drawer');dr.classList.add('open');
  document.getElementById('dtitle').textContent='Loading...';
  document.getElementById('dbody').innerHTML='';
  F('/api/conversations/'+encodeURIComponent(fanId)).then(function(d){
    if(!d){document.getElementById('dtitle').textContent='Error';return}
    var p=d.profile||{};
    document.getElementById('dtitle').textContent=p.display_name||d.fan_id.slice(0,12);
    var h='';
    // Profile pills
    h+='<div class="dsec"><h4>Profile</h4><div class="pill-row">';
    h+='<span class="pill">'+esc(p.spend_tier||'unknown')+'</span>';
    h+='<span class="pill">$'+((p.total_spent||0).toFixed(0))+' spent</span>';
    h+='<span class="pill">'+(p.purchase_count||0)+' buys</span>';
    if(p.occupation)h+='<span class="pill">'+esc(p.occupation)+'</span>';
    if(d.funnel_stage)h+='<span class="pill">'+esc(d.funnel_stage)+'</span>';
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
        h+='<div style="font-size:10px;color:var(--tx3);margin-top:4px">'+esc(sq.status)+(sq.last_sent_at?' &middot; '+ft(sq.last_sent_at):'')+'</div></div>';
      });
      h+='</div>';
    }
    // Remembered facts
    h+='<div class="dsec"><h4>Remembered ('+(d.facts||[]).length+' facts)</h4>';
    if(d.facts&&d.facts.length){h+='<ul class="fact-list">';d.facts.forEach(function(f){h+='<li>'+esc(f)+'</li>'});h+='</ul>'}
    else h+='<p style="font-size:12px;color:var(--tx3)">No facts learned yet — the bot extracts facts from every 3rd fan message.</p>';
    h+='</div>';
    // Writing style mirror
    if(d.style&&d.style.formality!=='unknown'){
      h+='<div class="dsec"><h4>Style Mirror</h4><div class="pill-row">';
      h+='<span class="pill">'+esc(d.style.formality)+'</span>';
      h+='<span class="pill">~'+d.style.avg_length+' chars</span>';
      h+='<span class="pill">'+d.style.emoji_rate+' emoji/msg</span>';
      if(d.style.uses_abbreviations)h+='<span class="pill">abbrev</span>';
      (d.style.slang||[]).forEach(function(x){h+='<span class="pill" style="border-color:rgba(113,112,255,.3);color:#a5a3ff">'+esc(x)+'</span>'});
      h+='</div></div>';
    }
    // Preferences & limits
    if((d.preferences&&d.preferences.length)||(d.hard_limits&&d.hard_limits.length)){
      h+='<div class="dsec"><h4>Preferences &amp; Boundaries</h4><div class="pill-row">';
      (d.preferences||[]).forEach(function(x){h+='<span class="pill">'+esc(x)+'</span>'});
      (d.hard_limits||[]).forEach(function(x){h+='<span class="pill" style="border-color:rgba(248,113,113,.3);color:#f87171">'+esc(x)+'</span>'});
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
async function loadBotStatus(){
  try{
    var r=await fetch('/api/bot/status',{credentials:'same-origin',cache:'no-store'});
    var d=await r.json();
    updateToggleUI(Boolean(d.enabled),Boolean(d.available),d.reason||'',d.consistent!==false);
  }catch(e){
    updateToggleUI(false,false,'Status request failed',false);
  }
}
function updateToggleUI(enabled,available,reason,consistent){
  var dot=document.getElementById('dot');
  var label=document.getElementById('toggle-label');
  var button=document.getElementById('bot-toggle');
  if(!dot||!label)return;
  dot.className='dot'+(enabled&&available?'':' off');
  label.textContent=!available?'Bot unavailable':enabled?'Bot on':'Bot off';
  label.style.color=enabled?'var(--green)':'var(--red)';
  if(button){
    button.disabled=!available;
    button.title=reason||(!consistent?'Runtime and persisted state disagree':'');
    button.setAttribute('aria-pressed',enabled?'true':'false');
    button.setAttribute('aria-label',!available?'Bot unavailable':enabled?'Turn bot off':'Turn bot on');
  }
}
async function toggleBot(){
  var button=document.getElementById('bot-toggle');
  if(!button||button.disabled)return;
  var target=button.getAttribute('aria-pressed')!=='true';
  button.disabled=true;
  try{
    var r=await M('/api/bot/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:target})});
    var d=await r.json();
    if(!r.ok)throw new Error(d.error||'Toggle failed');
    updateToggleUI(Boolean(d.enabled),Boolean(d.available),d.reason||'',d.consistent!==false);
  }catch(e){
    button.title=e.message||'Toggle failed';
    await loadBotStatus();
  }
}

function loadVault(){
  var c=document.getElementById('content');
  F('/api/vault').then(function(d){
    if(!d){c.innerHTML=emptyState('&#9633;','Vault unavailable','The local media directory could not be read.');return}
    var h='<div class="block"><h3>Local files only</h3><p style="font-size:12px;color:var(--amber)">'+esc(d.reason||'These files are not provider media IDs.')+'</p></div>';
    if(!d.files||!d.files.length){h+=emptyState('&#9633;','No local media files','Files in '+esc(d.dir||'/data/videos')+' are storage only until they are uploaded through OnlyFansAPI.');c.innerHTML=h;return}
    h+='<div class="media-grid">';d.files.forEach(function(f){var i=f.type==='video'?'&#127916;':f.type==='image'?'&#128444;':'&#128196;';h+='<div class="media-card"><div class="ico">'+i+'</div><div class="name">'+esc(f.name)+'</div><div class="size">'+esc(f.size)+'</div><div style="font-size:10px;color:var(--amber);margin-top:5px">Not provider-ready</div></div>'});h+='</div>';c.innerHTML=h;
  });
}

function loadFans(){
  var c=document.getElementById('content');
  F('/api/fans').then(function(d){
    if(!d||!d.fans||!d.fans.length){c.innerHTML=emptyState('&#9675;','No fan profiles yet','Profiles build automatically as conversations create memories, preferences, and purchase history.');return}
    var h='<div class="panel"><table><thead><tr><th>Fan</th><th>Tier</th><th>Spent</th><th>Buys</th><th>Stage</th><th>Preferences</th></tr></thead><tbody>';
    d.fans.forEach(function(f){var fid=String(f.fan_id||'');h+='<tr><td style="color:var(--tx)">'+esc(f.display_name||fid.slice(0,10))+'</td><td>'+B(f.spend_tier==='whale'?'whale':f.spend_tier==='average'?'avg':'low',f.spend_tier)+'</td><td>$'+Number(f.total_spent||0).toFixed(0)+'</td><td>'+Number(f.purchase_count||0)+'</td><td>'+esc(f.relationship_stage||'new')+'</td><td style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+esc((f.preferences||[]).join(', ')||'\u2014')+'</td></tr>'});
    h+='</tbody></table></div>';c.innerHTML=h;
  });
}

function loadScripts(){
  var c=document.getElementById('content');
  F('/api/scripts').then(function(d){
    if(!d||!d.scripts||!d.scripts.length){c.innerHTML=emptyState('&#9998;','No scripts loaded','Add conversation scripts to give the bot repeatable, on-brand playbooks.');return}
    var by={};d.scripts.forEach(function(s){if(!by[s.category])by[s.category]=[];by[s.category].push(s)});
    var h='';Object.entries(by).forEach(function(e){var cat=e[0],ss=e[1];h+='<div class="cat"><h4>'+esc(cat)+'</h4><div class="panel"><table><thead><tr><th>Name</th><th>Msgs</th><th>Description</th></tr></thead><tbody>';
    ss.forEach(function(s){h+='<tr><td style="color:var(--tx)">'+esc(s.name)+'</td><td>'+Number(s.message_count||0)+'</td><td>'+esc(s.description)+'</td></tr>'});
    h+='</tbody></table></div></div>'});
    c.innerHTML=h||emptyState('&#9998;','No scripts loaded','Add conversation scripts to give the bot repeatable, on-brand playbooks.');
  });
}

function loadKPIs(){
  var c=document.getElementById('content');
  F('/api/kpis').then(function(d){
    if(!d){c.innerHTML=emptyState('&#8599;','No KPI data yet','Performance metrics will populate as conversations and purchases are recorded.');return}
    var pct=d.ppv_unlock_rate==null?'N/A':Number(d.ppv_unlock_rate).toFixed(1)+'%';
    var aov=d.aov==null?'N/A':'$'+Number(d.aov).toFixed(2);
    var response=d.response_time_avg==null?'N/A':Number(d.response_time_avg).toFixed(1)+'s';
    var balance=d.wallet_latest_balance==null?'N/A':'$'+Number(d.wallet_latest_balance).toFixed(2);
    var cards=[
      {l:'Attributed Revenue',v:'$'+Number(d.attributed_revenue||0).toFixed(2),c:'up'},
      {l:'Attributed Purchases',v:Number(d.attributed_purchases||0),c:'up'},
      {l:'PPV Unlock Rate',v:pct,c:d.ppv_unlock_rate==null?'warn':'up'},
      {l:'Average Order Value',v:aov,c:d.aov==null?'warn':'up'},
      {l:'Average Response',v:response,c:d.response_time_avg==null?'warn':'up'},
      {l:'Sent Messages',v:Number(d.sent_outbounds||0),c:'up'},
      {l:'Known Fans',v:Number(d.known_fans||0),c:'up'},
      {l:'Blocked PPV Intents',v:Number(d.blocked_ppv_intents||0),c:d.blocked_ppv_intents?'warn':'up'},
      {l:'Wallet Balance',v:balance,c:'avg'}
    ];
    c.innerHTML='<div class="block"><p style="font-size:12px;color:var(--tx3)">Revenue and purchases below use only exact attributed purchase events. Wallet balance is aggregate and is not assigned to any fan.</p></div><div class="cards">'+cards.map(function(card){return'<div class="card"><h3>'+esc(card.l)+'</h3><div class="v '+attr(card.c)+'\">'+esc(card.v)+'</div></div>'}).join('')+'</div>';
  });
}

function loadSettings(){
  var c=document.getElementById('content');
  var h='<div class="block"><h3>API connection</h3><div class="g3" id="api-status">Loading...</div><div style="margin-top:14px"><button class="btn-ghost" data-action="test-connection">Test connection</button> <span id="conn-result"></span></div></div>';
  h+='<div class="block"><h3>Persona</h3><div class="row"><input id="psel" value="" readonly aria-label="Creator ID"/><button class="btn-ghost" data-action="load-persona">Reload</button><span class="done" id="psaved">Applied</span></div><label>Validated creator persona used by the live bot</label><textarea id="ped" placeholder="tone: flirty&#10;signature_phrases:&#10;  - hey babe"></textarea><div style="margin-top:10px"><button class="btn" data-action="save-persona">Validate, save, and apply</button> <span id="perror" style="font-size:11px;color:var(--red)"></span></div></div>';
  h+='<div class="block"><h3>Brand Bible</h3><p style="font-size:12px;color:var(--amber);margin-bottom:10px">Reference document only. The bot does not currently read this file at runtime.</p><textarea id="bed" placeholder="# Brand Bible&#10;&#10;## Voice..."></textarea><div style="margin-top:10px"><button class="btn" data-action="save-brand-bible">Save reference</button> <span class="done" id="bsaved">Saved as reference</span></div></div>';
  c.innerHTML=h;loadConn();loadPersona();loadBrandBible();
}
function loadConn(){F('/api/connection').then(function(d){var el=document.getElementById('api-status');if(!d){el.innerHTML='<div class="card"><h3>Error</h3><div style="font-size:12px;color:#f87171">Failed</div></div>';return}el.innerHTML='<div class="card"><h3>Account</h3><div style="font-size:12px">'+esc(d.account_id||'Unavailable')+'</div></div><div class="card"><h3>API</h3><div class="v '+(d.connected?'up':'bad')+'" style="font-size:16px">'+esc(d.status||'offline')+'</div><div style="font-size:10px;color:var(--tx3)">'+esc(d.error||'')+'</div></div><div class="card"><h3>Provider</h3><div style="font-size:11px;color:var(--tx3)">'+esc(d.provider||'OnlyFansAPI Fansly')+'</div></div>'})}
function testConn(){var el=document.getElementById('conn-result');el.textContent='Testing\u2026';el.style.color='var(--tx3)';M('/api/connection/test',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(function(r){return r.json()}).then(function(d){var ok=d&&d.connected;el.textContent=ok?'Live verification passed':'Failed: '+(d.error||'unknown');el.style.color=ok?'var(--green)':'#f87171';loadConn()}).catch(function(){el.textContent='Connection test failed';el.style.color='var(--red)'})}
function loadPersona(){var m=document.getElementById('psel').value;var url='/api/persona'+(m?'?creator='+encodeURIComponent(m):'');F(url).then(function(d){if(!d)return;document.getElementById('psel').value=d.creator_id||m;document.getElementById('ped').value=d.yaml||''})}
function savePersona(){var m=document.getElementById('psel').value,y=document.getElementById('ped').value;var error=document.getElementById('perror');error.textContent='';M('/api/persona?creator='+encodeURIComponent(m),{method:'POST',headers:{'Content-Type':'text/yaml; charset=utf-8'},body:y}).then(async function(r){var d=await r.json();var el=document.getElementById('psaved');if(!r.ok){error.textContent=d.error||'Save failed';return}el.textContent=d.runtime_applied?'Applied now':'Saved for next bot start';el.style.display='flex';setTimeout(function(){el.style.display='none'},2500)})}
function loadBrandBible(){F('/api/brand-bible').then(function(d){document.getElementById('bed').value=d&&d.content||''})}
function saveBible(){var c=document.getElementById('bed').value;M('/api/brand-bible',{method:'POST',headers:{'Content-Type':'text/markdown; charset=utf-8'},body:c}).then(function(r){var el=document.getElementById('bsaved');if(r.ok){el.style.display='flex';setTimeout(function(){el.style.display='none'},2000)}})}

// ═══ PPV SEQUENCES ════════════════════════════════════
function loadSequences(){
  var c=document.getElementById('content');
  F('/api/sequences').then(function(d){
    var seqs=d&&d.sequences||[];
    dashboardSequenceEditingAvailable=Boolean(d&&d.editing_available);
    dashboardPaidMessagesSupported=Boolean(d&&d.paid_messages_supported);
    dashboardPpvReason=d&&d.blocked_reason||'Paid Fansly messaging is unavailable.';
    var action='<button class="btn" data-action="new-sequence"'+(dashboardSequenceEditingAvailable?'':' disabled')+'>New draft</button>';
    var description=!dashboardSequenceEditingAvailable?'Sequence storage is unavailable because the bot did not initialize.':dashboardPaidMessagesSupported?'Paid delivery is supported by the configured provider.':'Sequences can be edited as inactive drafts, but cannot be activated or delivered.';
    var h=sectionIntro('PPV sequence drafts',description,action);
    if(!dashboardPaidMessagesSupported)h+='<div class="block"><p style="font-size:12px;color:var(--amber)">'+esc(dashboardPpvReason)+'</p></div>';
    if(!seqs.length){h+=emptyState('&#8644;','No sequences yet','Create a PPV ladder to automate a consistent offer journey for each fan segment.');c.innerHTML=h;return}
    h+='<div class="panel"><table><thead><tr><th>Name</th><th>Trigger</th><th>Steps</th><th>Total</th><th>Delivery state</th><th></th></tr></thead><tbody>';
    seqs.forEach(function(s){var sid=Number(s.id);var state=s.effective_active?'<span style="color:var(--green)">Active</span>':s.is_active?'<span style="color:var(--amber)">Blocked</span>':'<span style="color:var(--tx3)">Inactive draft</span>';h+='<tr class="clickable" data-action="edit-sequence" data-sequence-id="'+sid+'"><td style="color:var(--tx)">'+esc(s.name)+'</td><td><span class="badge '+(s.trigger=='whale'?'whale':s.trigger=='re_engage'?'bad':'avg')+'\">'+esc(s.trigger)+'</span></td><td>'+Number(s.step_count||0)+'</td><td>$'+Number(s.total_price||0).toFixed(0)+'</td><td>'+state+'</td><td><button class="btn-ghost" data-action="delete-sequence" data-sequence-id="'+sid+'">&#128465;</button></td></tr>'});
    h+='</tbody></table></div>';c.innerHTML=h;
  });
}
var editSeqId=null;
var dashboardAlbums=[];
var dashboardSteps=[];
var dashboardSequenceEditingAvailable=false;
var dashboardPaidMessagesSupported=false;
var dashboardPpvReason='';
var dashboardVaultAlbumsSupported=false;
var dashboardVaultReason='';
function newSequence(){if(!dashboardSequenceEditingAvailable)return;editSeqId=null;openSeqEditor({name:'',trigger:'welcome',funnel_stage:'rapport',is_active:false,steps:[],paid_messages_supported:dashboardPaidMessagesSupported})}
function editSeq(id){
  F('/api/sequences/'+id).then(function(d){
    if(!d)return;editSeqId=d.id;openSeqEditor(d);
  });
}
function openSeqEditor(s){
  var c=document.getElementById('content');
  dashboardPaidMessagesSupported=Boolean(s.paid_messages_supported||dashboardPaidMessagesSupported);
  dashboardPpvReason=s.blocked_reason||dashboardPpvReason;
  var triggers=['new_sub','welcome','rapport','whale','re_engage','manual'];
  var h='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px"><h3 style="font-size:14px;font-weight:600">'+(editSeqId?'Edit':'New')+' Sequence</h3><div><button class="btn-ghost" data-action="load-sequences" style="margin-right:8px">&#8592; Back</button><button class="btn" data-action="save-sequence">&#128190; Save</button></div></div>';
  h+='<div class="panel" style="padding:18px;margin-bottom:14px"><div class="g3" style="margin-bottom:12px">';
  h+='<div><label>Name</label><input id="sname" value="'+attr(s.name||'')+'" placeholder="e.g. Welcome Ladder"/></div>';
  h+='<div><label>Trigger</label><select id="strigger">'+triggers.map(function(t){return'<option value="'+t+'"'+(s.trigger==t?' selected':'')+'>'+t.replace('_',' ')+'</option>'}).join('')+'</select></div>';
  h+='<div><label>Funnel Stage</label><select id="sfunnel"><option value="rapport"'+(s.funnel_stage=='rapport'?' selected':'')+'>Rapport</option><option value="tease"'+(s.funnel_stage=='tease'?' selected':'')+'>Tease</option><option value="offer"'+(s.funnel_stage=='offer'?' selected':'')+'>Offer</option><option value="close"'+(s.funnel_stage=='close'?' selected':'')+'>Close</option></select></div>';
  h+='<div><label>Delivery state</label><select id="sactive"'+(dashboardPaidMessagesSupported?'':' disabled')+'><option value="1"'+(s.is_active&&dashboardPaidMessagesSupported?' selected':'')+'>Active</option><option value="0"'+(!s.is_active||!dashboardPaidMessagesSupported?' selected':'')+'>Inactive draft</option></select></div>';
  h+='</div></div>';
  if(!dashboardPaidMessagesSupported)h+='<div class="block"><p style="font-size:12px;color:var(--amber)">'+esc(dashboardPpvReason)+'</p></div>';
  h+='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px"><h4 style="font-size:12px;font-weight:500;color:var(--tx2)">Steps ('+((s.steps||[]).length)+')</h4><button class="btn-ghost" data-action="add-step">+ Add Step</button></div>';
  h+='<div id="steps-container"></div>';
  c.innerHTML=h;
  F('/api/vault-albums').then(function(d){
    dashboardAlbums=d&&d.albums||[];
    dashboardVaultAlbumsSupported=Boolean(d&&d.supported);
    dashboardVaultReason=d&&d.reason||d&&d.error||'Provider vault browsing is unavailable.';
    if(typeof renderSteps=='function')renderSteps(s.steps||[]);
    else setTimeout(function(){renderSteps(s.steps||[])},100);
  });
}
function renderSteps(steps){
  var el=document.getElementById('steps-container');if(!el)return;
  dashboardSteps=steps.map(function(s,i){
    return {position:i+1,media_id:s.media_id||'',preview_id:'',price:s.price||0,tease_script:s.tease_script||'',offer_script:s.offer_script||'',id:s.id||null};
  });
  if(!dashboardSteps.length){el.innerHTML='<div class="empty"><div class="ico">&#128196;</div><p>Add your first PPV step</p></div>';return}
  var h='';
  dashboardSteps.forEach(function(step,i){
    h+='<div class="panel" style="padding:14px;margin-bottom:8px;border-left:3px solid var(--accent)">';
    h+='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px"><span style="font-size:11px;font-weight:500;color:var(--accent)">PPV '+(i+1)+'</span><button class="btn-ghost" data-action="remove-step" data-step-index="'+i+'" style="padding:2px 8px;font-size:10px">&#128465; Remove</button></div>';
    h+='<div class="g3" style="margin-bottom:8px">';
    h+='<div><label>OnlyFansAPI media ID</label><div class="row" style="margin-bottom:0"><input id="smedia_'+i+'" value="'+attr(step.media_id||'')+'" placeholder="fansly_media_..." style="flex:1;margin-bottom:0"/><button class="btn-ghost" data-action="pick-media" data-step-index="'+i+'"'+(dashboardVaultAlbumsSupported?'':' disabled title="'+attr(dashboardVaultReason)+'"')+'>Browse</button></div></div>';
    h+='<div><label>Price ($)</label><input id="sprice_'+i+'" value="'+step.price.toFixed(2)+'"/></div></div>';
    h+='<div class="g3"><div><label>Tease Script</label><textarea id="stease_'+i+'" rows="2">'+esc(step.tease_script||'')+'</textarea></div>';
    h+='<div><label>Offer Script</label><textarea id="soffer_'+i+'" rows="2">'+esc(step.offer_script||'')+'</textarea></div></div></div>';
  });
  el.innerHTML=h;
}
function addStep(){var s=dashboardSteps;s.push({media_id:'',preview_id:'',price:0,tease_script:'',offer_script:''});renderSteps(s)}
function removeStep(idx){var s=dashboardSteps;s.splice(idx,1);renderSteps(s)}
function pickMedia(idx){
  var albums=dashboardAlbums;
  if(!dashboardVaultAlbumsSupported){alert(dashboardVaultReason);return}
  if(!albums.length){alert('No provider vault albums');return}
  var opts=albums.map(function(a){return'<option value="'+attr(a.id)+'">'+esc(a.name||'Album '+a.id)+'</option>'}).join('');
  var h='<div class="panel" style="padding:18px;max-height:300px;overflow-y:auto"><h4 style="font-size:12px;font-weight:500;margin-bottom:10px">Select from Vault</h4>';
  h+='<label>Album</label><select id="album-picker" data-step-index="'+idx+'">'+opts+'</select>';
  h+='<div id="album-media-list" style="margin-top:10px"><p style="font-size:12px;color:var(--tx3)">Select album</p></div></div>';
  var el=document.getElementById('steps-container');
  if(el)el.insertAdjacentHTML('afterbegin',h);
  if(albums.length)loadAlbumMedia(idx);
}
function loadAlbumMedia(idx){
  var sel=document.getElementById('album-picker');if(!sel)return;
  F('/api/vault-albums/'+encodeURIComponent(sel.value)+'/media').then(function(d){
    var items=d&&d.media||[];var el=document.getElementById('album-media-list');if(!el)return;
    if(!items.length){el.innerHTML='<p style="font-size:12px;color:var(--tx3)">No media</p>';return}
    var h='<div class="media-grid" style="margin-top:8px">';
    items.forEach(function(m){
      var typeI=m.type=='video'?'&#127916;':m.type=='image'?'&#128444;':'&#128196;';
      h+='<div class="media-card" style="cursor:pointer" data-action="select-media" data-step-index="'+idx+'" data-media-id="'+attr(m.id||m.mediaId)+'">';
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
  var steps=dashboardSteps;
  var stepData=steps.map(function(s,i){
    return {position:i+1,media_id:(document.getElementById('smedia_'+i)||{}).value||'',preview_id:'',price:parseFloat((document.getElementById('sprice_'+i)||{}).value)||0,tease_script:(document.getElementById('stease_'+i)||{}).value||'',offer_script:(document.getElementById('soffer_'+i)||{}).value||''};
  });
  var body={name:name,trigger:trigger,funnel_stage:funnel,is_active:active,steps:stepData};
  var url='/api/sequences'+(editSeqId?'/'+editSeqId:'');
  M(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(async function(r){
    var d=await r.json();
    if(!r.ok){alert(d.error||'Save failed');return}
    loadSequences();
  });
}
function deleteSeq(id){
  if(!confirm('Delete this sequence?'))return;
  M('/api/sequences/'+id,{method:'DELETE'}).then(function(r){if(r.ok)loadSequences()});
}

document.addEventListener('click',function(event){
  var nav=event.target.closest('.nav-item[data-tab]');
  if(nav){navTo(nav.dataset.tab);return}
  var control=event.target.closest('[data-action]');
  if(!control)return;
  var action=control.dataset.action;
  var stepIndex=Number(control.dataset.stepIndex);
  var sequenceId=Number(control.dataset.sequenceId);
  if(action==='toggle-bot')toggleBot();
  else if(action==='close-drawer')closeDrawer();
  else if(action==='fan-detail')fanDetail(control.dataset.fanId||'');
  else if(action==='test-connection')testConn();
  else if(action==='load-persona')loadPersona();
  else if(action==='save-persona')savePersona();
  else if(action==='save-brand-bible')saveBible();
  else if(action==='new-sequence')newSequence();
  else if(action==='load-sequences')loadSequences();
  else if(action==='save-sequence')saveSeq();
  else if(action==='edit-sequence'&&Number.isInteger(sequenceId))editSeq(sequenceId);
  else if(action==='delete-sequence'&&Number.isInteger(sequenceId))deleteSeq(sequenceId);
  else if(action==='add-step')addStep();
  else if(action==='remove-step'&&Number.isInteger(stepIndex))removeStep(stepIndex);
  else if(action==='pick-media'&&Number.isInteger(stepIndex))pickMedia(stepIndex);
  else if(action==='select-media'&&Number.isInteger(stepIndex))selectMedia(stepIndex,control.dataset.mediaId||'');
});
document.addEventListener('change',function(event){
  if(event.target.id==='psel')loadPersona();
  if(event.target.id==='album-picker'){
    var stepIndex=Number(event.target.dataset.stepIndex);
    if(Number.isInteger(stepIndex))loadAlbumMedia(stepIndex);
  }
});

loadBotStatus();
setInterval(function(){loadBotStatus()},15000);
loadFunnel();
setInterval(function(){loadFunnel()},60000);
</script>
</body>
</html>"""

# Keep the dashboard presentation separate from the HTTP and API logic. The
# public module-level name remains unchanged for callers and regression tests.
DASHBOARD_HTML = (
    Path(__file__).with_name("dashboard_shell.html").read_text(encoding="utf-8")
)

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

def _spend_tier(total_spent: float) -> str:
    if total_spent >= 500:
        return "whale"
    if total_spent >= 50:
        return "average"
    return "time_waster"


def _note(n, purchase=None):
    if n is None: return None
    total_spent = (
        purchase.total_spent_millis / 1000
        if purchase is not None
        else 0.0
    )
    purchase_count = (
        purchase.purchase_count if purchase is not None else 0
    )
    last_purchase_at = (
        purchase.last_purchase_at if purchase is not None else None
    )
    return {"fan_id":n.fan_id,"display_name":n.display_name,"preferences":n.preferences,"occupation":n.occupation,"total_spent":total_spent,"purchase_count":purchase_count,"last_purchase_at":last_purchase_at.isoformat() if last_purchase_at else None,"emotional_triggers":n.emotional_triggers,"hard_limits":n.hard_limits,"facts":n.facts,"notes":n.notes,"relationship_stage":n.relationship_stage,"spend_tier":_spend_tier(total_spent),"purchase_source":"attributed_provider_events"}

def _script(s):
    return {
        "name":s.name,
        "category":(
            s.category.value
            if hasattr(s.category,"value")
            else str(s.category)
        ),
        "description":s.description,
        "messages":list(s.messages),
        "message_count":len(s.messages),
        "variables":[
            variable.model_dump()
            for variable in getattr(s,"variables",[])
        ],
        "conditions":dict(getattr(s,"conditions",{})),
    }

def _body(h):
    raw_length = h.headers.get("Content-Length", "0")
    try:
        length = int(raw_length)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid content length") from exc
    if length < 0:
        raise ValueError("invalid content length")
    if length > MAX_BODY_BYTES:
        raise PayloadTooLargeError("request body too large")
    try:
        return h.rfile.read(length).decode("utf-8") if length else ""
    except UnicodeDecodeError as exc:
        raise ValueError("request body must be UTF-8") from exc

class DashboardHandler(BaseHTTPRequestHandler):
    @property
    def bot(self):
        return self.server.bot

    @property
    def vault_dir(self):
        return self.server.vault_dir

    @property
    def engine(self):
        return self.server.engine

    @property
    def client(self):
        return self.server.client

    @property
    def creator_id(self):
        return self.server.creator_id

    @property
    def dashboard_repo(self) -> DashboardReadRepository | None:
        if self.engine is None:
            return None
        return DashboardReadRepository(self.engine)

    @property
    def crm_sync(self):
        return getattr(self.server, "crm_sync", None)

    @property
    def script_repo(self) -> ScriptTemplateRepository | None:
        return getattr(self.server, "script_repo", None)

    @property
    def media_repo(self) -> MediaAssetRepository | None:
        return getattr(self.server, "media_repo", None)

    @property
    def ai_settings(self):
        return getattr(self.server, "ai_settings", None)

    def _security_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")

    def _write(self, payload, content_type, status=200, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self._security_headers()
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def j(self, data, status=200, extra_headers=None):
        payload = json.dumps(data, default=str, separators=(",", ":")).encode("utf-8")
        self._write(payload, "application/json; charset=utf-8", status, extra_headers)

    def h(self, html, status=200):
        nonce = secrets.token_urlsafe(18)
        rendered = (
            html.replace("__CSP_NONCE__", nonce)
            .replace("__CSRF_TOKEN__", json.dumps(self.server.csrf_token))
        )
        payload = rendered.encode("utf-8")
        csp = (
            "default-src 'self'; "
            f"script-src 'nonce-{nonce}'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "media-src 'self' https:; "
            "connect-src 'self'; "
            "font-src 'self'; "
            "object-src 'none'; "
            "base-uri 'none'; "
            "frame-ancestors 'none'; "
            "form-action 'self'"
        )
        self._write(
            payload,
            "text/html; charset=utf-8",
            status,
            {"Content-Security-Policy": csp},
        )

    def _host_is_allowed(self):
        host = self.headers.get("Host", "")
        try:
            hostname = urlsplit(f"//{host}").hostname
        except ValueError:
            return False
        if not hostname:
            return False
        normalized = hostname.lower()
        if normalized == "healthcheck.railway.app":
            return self.path.split("?", 1)[0] in {"/health", "/ready"}
        return normalized in self.server.allowed_hosts

    def _database_ready(self) -> bool:
        if self.engine is None:
            return False
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:
            logger.exception("Database readiness check failed")
            return False

    def _is_authenticated(self):
        expected_user = self.server.dashboard_user
        expected_password = self.server.dashboard_password
        if not expected_user or len(expected_password) < 16:
            return None

        supplied_user = ""
        supplied_password = ""
        authorization = self.headers.get("Authorization", "")
        try:
            scheme, encoded = authorization.split(" ", 1)
            if scheme.lower() == "basic":
                decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
                supplied_user, supplied_password = decoded.split(":", 1)
        except (ValueError, UnicodeDecodeError, binascii.Error):
            pass

        user_ok = hmac.compare_digest(
            supplied_user.encode("utf-8"), expected_user.encode("utf-8")
        )
        password_ok = hmac.compare_digest(
            supplied_password.encode("utf-8"), expected_password.encode("utf-8")
        )
        return user_ok and password_ok

    def _csrf_is_valid(self):
        supplied = self.headers.get("X-CSRF-Token", "")
        token_ok = hmac.compare_digest(
            supplied.encode("utf-8"), self.server.csrf_token.encode("utf-8")
        )
        if not token_ok:
            return False

        if self.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
            return False

        origin = self.headers.get("Origin")
        if not origin:
            return True
        try:
            parsed = urlsplit(origin)
        except ValueError:
            return False
        return (
            parsed.scheme in {"http", "https"}
            and parsed.netloc.lower() == self.headers.get("Host", "").lower()
        )

    def _authorize(self, require_csrf=False):
        if not self._host_is_allowed():
            self.j({"error": "invalid host"}, 400)
            return False

        authenticated = self._is_authenticated()
        if authenticated is None:
            self.j({"error": "dashboard credentials are not configured"}, 503)
            return False
        if not authenticated:
            self.j(
                {"error": "authentication required"},
                401,
                {"WWW-Authenticate": 'Basic realm="Fansly Dashboard", charset="UTF-8"'},
            )
            return False
        if require_csrf and not self._csrf_is_valid():
            self.j({"error": "invalid CSRF token or request origin"}, 403)
            return False
        return True

    def do_GET(self):
        p = self.path.split("?")[0]; q = parse_qs(self.path.split("?")[1]) if "?" in self.path else {}
        if not self._host_is_allowed():
            return self.j({"error": "invalid host"}, 400)
        if p=="/health": return self.j({"status":"ok","service":"fansly-bot"})
        if p=="/ready":
            ready = self._database_ready()
            return self.j(
                {"status":"ready" if ready else "not_ready","service":"fansly-bot"},
                200 if ready else 503,
            )
        if not self._authorize():
            return
        if p in ("/","/dashboard"): return self.h(DASHBOARD_HTML)
        if p=="/api/conversations": return self._conv(q)
        if p.startswith("/api/conversations/"): return self._conv_detail(p.rsplit("/",1)[-1], q)
        if p=="/api/fans": return self._fans()
        if p=="/api/vault": return self._vault()
        if p=="/api/media-assets": return self._media_assets(q)
        if p=="/api/kpis": return self._kpi()
        if p=="/api/scripts": return self._scrs()
        if p=="/api/connection": return self._conn(False)
        if p=="/api/ai/settings": return self._ai_settings_get()
        if p=="/api/chat-instructions": return self._chat_instructions_get()
        if p=="/api/persona": return self._pers_get(q)
        if p=="/api/brand-bible": return self._bible_get()
        if p=="/api/sequences": return self._seq_list()
        if p.startswith("/api/sequences/") and len(p.split("/"))==4: return self._seq_get(p.rsplit("/",1)[-1])
        if p=="/api/vault-albums": return self._vault_albums()
        if p.startswith("/api/vault-albums/") and p.endswith("/media"): return self._vault_album_media(p.split("/")[-2])
        if p.startswith("/api/fan-progress/"): return self._fan_progress(p.rsplit("/",1)[-1])
        if p=="/api/bot/status": return self._bot_status()
        if p=="/api/operations": return self._operations()
        self.j({"error":"not found"},404)

    def do_POST(self):
        p = self.path.split("?")[0]
        if p.startswith("/webhooks/apifansly/"):
            return self._apifansly_webhook(p)
        if not self._authorize(require_csrf=True):
            return
        q = parse_qs(self.path.split("?")[1]) if "?" in self.path else {}
        try:
            b = _body(self)
        except PayloadTooLargeError:
            return self.j({"error": "request body too large"}, 413)
        except ValueError:
            return self.j({"error": "invalid request body"}, 400)
        if p=="/api/persona": return self._pers_post(q,b)
        if p=="/api/brand-bible": return self._bible_post(b)
        if p=="/api/connection/test": return self._conn(True)
        if p=="/api/ai/settings": return self._ai_settings_save(b)
        if p=="/api/ai/connection/test": return self._ai_connection_test()
        if p=="/api/chat-instructions": return self._chat_instructions_post(b)
        if p=="/api/scripts": return self._script_save(b)
        if p.startswith("/api/scripts/") and len(p.split("/"))==4: return self._script_save(b,p.rsplit("/",1)[-1])
        if p=="/api/media-assets": return self._media_asset_save(b)
        if p=="/api/sequences": return self._seq_create(b)
        if p.startswith("/api/sequences/") and len(p.split("/"))==4: return self._seq_update(p.rsplit("/",1)[-1], b)
        if p=="/api/bot/toggle": return self._bot_toggle(b)
        self.j({"error":"not found"},404)

    def _apifansly_webhook(self, path: str):
        """Ingest an exact APIFansly PPV purchase without dashboard auth."""
        if not self._host_is_allowed():
            return self.j({"error": "invalid host"}, 400)
        expected_token = self.server.apifansly_webhook_token
        supplied_token = path.rsplit("/", 1)[-1]
        if (
            path.count("/") != 3
            or len(expected_token) < 32
            or not hmac.compare_digest(
                supplied_token.encode("utf-8"),
                expected_token.encode("utf-8"),
            )
        ):
            return self.j({"error": "not found"}, 404)
        try:
            raw = _body(self)
            payload = json.loads(raw)
        except PayloadTooLargeError:
            return self.j({"error": "request body too large"}, 413)
        except (ValueError, json.JSONDecodeError):
            return self.j({"error": "invalid JSON payload"}, 400)
        if not isinstance(payload, dict):
            return self.j({"error": "invalid webhook payload"}, 400)
        if payload.get("event") != "ppv.purchased":
            return self.j({"accepted": False, "ignored": True}, 202)
        if self.bot is None:
            return self.j({"error": "bot is unavailable"}, 503)

        data = payload.get("data")
        if not isinstance(data, dict):
            return self.j({"error": "missing webhook data"}, 400)
        provider_account_id = str(payload.get("accountId", "")).strip()
        expected_account_id = str(
            getattr(self.client, "account_id", "")
        ).strip()
        if (
            not provider_account_id
            or provider_account_id != expected_account_id
        ):
            return self.j({"error": "webhook account mismatch"}, 403)

        order_id = str(data.get("orderId", "")).strip()
        purchase_ref = str(data.get("accountMediaId", "")).strip()
        fan_id = str(data.get("accountId", "")).strip()
        creator_fansly_id = str(
            data.get("correlationAccountId", "")
        ).strip()
        known_creator_fansly_id = str(
            getattr(self.client, "_creator_fansly_id", "") or ""
        ).strip()
        if (
            known_creator_fansly_id
            and creator_fansly_id != known_creator_fansly_id
        ):
            return self.j({"error": "webhook creator mismatch"}, 403)
        if not all(
            (order_id, purchase_ref, fan_id, creator_fansly_id)
        ):
            return self.j({"error": "incomplete PPV purchase event"}, 400)

        metadata = data.get("orderMetadata")
        price_cents = (
            metadata.get("accountMediaPrice")
            if isinstance(metadata, dict)
            else None
        )
        if isinstance(price_cents, bool):
            return self.j({"error": "invalid PPV price"}, 400)
        try:
            numeric_price_cents = float(price_cents)
        except (TypeError, ValueError):
            return self.j({"error": "invalid PPV price"}, 400)
        if not math.isfinite(numeric_price_cents) or not (
            numeric_price_cents.is_integer()
        ):
            return self.j({"error": "invalid PPV price"}, 400)
        amount_millis = int(numeric_price_cents) * 10
        if amount_millis <= 0:
            return self.j({"error": "invalid PPV price"}, 400)

        try:
            provider_created_at = datetime.fromisoformat(
                str(payload.get("timestamp", "")).replace(
                    "Z",
                    "+00:00",
                )
            )
        except ValueError:
            return self.j({"error": "invalid webhook timestamp"}, 400)
        if provider_created_at.tzinfo is None:
            provider_created_at = provider_created_at.replace(
                tzinfo=timezone.utc
            )

        try:
            _, created = self.bot.record_provider_ppv_purchase(
                provider_purchase_id=order_id,
                provider_purchase_ref=purchase_ref,
                fan_id=fan_id,
                amount_millis=amount_millis,
                provider_created_at=provider_created_at,
            )
        except ValueError as exc:
            logger.warning(
                "Rejected APIFansly PPV purchase event: %s",
                exc,
            )
            return self.j(
                {"error": "purchase does not match a sent PPV"},
                409,
            )
        except Exception:
            logger.exception("APIFansly PPV webhook processing failed")
            return self.j({"error": "webhook processing failed"}, 500)
        return self.j(
            {
                "accepted": True,
                "duplicate": not created,
            }
        )

    def do_DELETE(self):
        if not self._authorize(require_csrf=True):
            return
        p = self.path.split("?")[0]
        if p.startswith("/api/scripts/") and len(p.split("/"))==4: return self._script_delete(p.rsplit("/",1)[-1])
        if p.startswith("/api/media-assets/") and len(p.split("/"))==4: return self._media_asset_delete(p.rsplit("/",1)[-1])
        if p.startswith("/api/sequences/") and len(p.split("/"))==4: return self._seq_delete(p.rsplit("/",1)[-1])
        self.j({"error":"not found"},404)

    def do_OPTIONS(self):
        self.j({"error": "method not allowed"}, 405)

    def _list_notes(self):
        from ..notes.repository import FAN_NOTES_TABLE, _row_to_note
        rows = []
        if self.engine is None:
            return rows
        try:
            with self.engine.connect() as c:
                r = c.execute(FAN_NOTES_TABLE.select().where(FAN_NOTES_TABLE.c.creator_id==self.creator_id))
                for row in r:
                    try: rows.append(_row_to_note(row))
                    except: pass
        except: pass
        return rows

    def _purchase_totals(self):
        repository = self.dashboard_repo
        if repository is None:
            return {}
        return repository.fan_purchase_totals(self.creator_id)

    def _conv(self, query=None):
        repository=self.dashboard_repo
        if repository is None:
            return self.j({
                "fans":[],
                "total":0,
                "offset":0,
                "limit":200,
                "has_more":False,
                "live_sync_available":False,
                "source":"durable_state_unavailable",
            })
        query=query or {}
        try:
            limit=min(max(int((query.get("limit") or ["200"])[0]),1),500)
            offset=max(int((query.get("offset") or ["0"])[0]),0)
        except (TypeError,ValueError):
            return self.j({"error":"invalid conversation pagination"},400)
        search=str((query.get("search") or [""])[0]).strip()
        page=repository.conversation_page(
            self.creator_id,
            limit=limit,
            offset=offset,
            search=search,
        )
        provider_primed=False
        provider_refresh_error=None
        if (
            page.total == 0
            and offset == 0
            and not search
            and self.crm_sync is not None
        ):
            try:
                self.crm_sync.refresh_chat_index()
                provider_primed=True
                page=repository.conversation_page(
                    self.creator_id,
                    limit=limit,
                    offset=offset,
                    search=search,
                )
            except Exception as error:
                logger.exception("Live CRM chat-index refresh failed")
                provider_refresh_error=type(error).__name__
        purchases = self._purchase_totals()
        notes={note.fan_id:note for note in self._list_notes()}
        fans = []
        seen=set()
        for durable in page.conversations:
            fid=durable.fan_id
            seen.add(fid)
            n=notes.get(fid)
            purchase = purchases.get(fid)
            total_spent = (
                purchase.total_spent_millis / 1000
                if purchase is not None
                else 0.0
            )
            sess=(
                self.bot.sessions.get(fid)
                if self.bot is not None
                else None
            )
            fans.append({"fan_id":fid,"display_name":n.display_name if n and n.display_name else durable.display_name,"username":durable.username,"avatar_url":durable.avatar_url,"spend_tier":_spend_tier(total_spent),"funnel_stage":sess.funnel.current_stage.value if sess else durable.phase,"spiral_level":sess.funnel.level.number if sess else durable.escalation_level,"cooldown":sess.funnel.cooldown if sess else durable.cooldown,"message_count":durable.message_count,"last_activity":durable.last_activity_at.isoformat() if durable.last_activity_at else None,"fact_count":len(n.facts) if n else 0,"history_complete":durable.history_complete,"sync_error":durable.sync_error})
        if self.bot is not None and offset == 0 and not search:
            for fid,sess in self.bot.sessions.items():
                if fid in seen:
                    continue
                n=notes.get(fid)
                purchase=purchases.get(fid)
                total_spent=(
                    purchase.total_spent_millis/1000
                    if purchase is not None
                    else 0.0
                )
                fans.append({"fan_id":fid,"display_name":n.display_name if n else None,"spend_tier":_spend_tier(total_spent),"funnel_stage":sess.funnel.current_stage.value,"spiral_level":sess.funnel.level.number,"cooldown":sess.funnel.cooldown,"message_count":sess.message_count,"last_activity":sess.last_activity.isoformat() if sess.last_activity else None,"fact_count":len(n.facts) if n else 0})
        presence=PresenceRepository(self.engine).for_fans(
            self.creator_id,
            [str(fan["fan_id"]) for fan in fans],
        )
        for fan in fans:
            fan.update(presence.get(str(fan["fan_id"]),{
                "presence":"unknown",
                "last_seen_at":None,
                "last_outreach_at":None,
            }))
        fans.sort(key=lambda f:f.get("last_activity")or"",reverse=True)
        discovery_complete=None
        if self.crm_sync is not None:
            try:
                value=self.crm_sync.discovery_complete()
                if isinstance(value,bool):
                    discovery_complete=value
            except Exception:
                logger.exception("CRM discovery status read failed")
        return self.j({
            "fans":fans,
            "total":max(
                page.total,
                len(fans) if offset == 0 else page.total,
            ),
            "offset":page.offset,
            "limit":page.limit,
            "has_more":page.has_more,
            "provider_primed":provider_primed,
            "provider_refresh_error":provider_refresh_error,
            "discovery_complete":discovery_complete,
            "live_sync_available":self.crm_sync is not None,
            "source":"durable_state_with_live_overlay",
        })

    def _conv_detail(self, fan_id, query=None):
        """Full memory view for one fan: profile, remembered facts, message history."""
        if self.engine is None:
            return self.j({"error":"durable state unavailable"},503)
        from ..memory.store import MessageStore
        from ..notes.repository import FanNoteRepository
        from ..persistence.state import ConversationStateRepository
        note_repo=(
            self.bot.note_repo
            if self.bot is not None
            else FanNoteRepository(engine=self.engine)
        )
        note = note_repo.get(fan_id, self.creator_id)
        purchase = self._purchase_totals().get(fan_id)
        message_store=(
            self.bot.message_store
            if self.bot is not None and self.bot.message_store
            else MessageStore(engine=self.engine)
        )
        query=query or {}
        try:
            message_limit=min(max(int((query.get("limit") or ["100"])[0]),1),250)
            message_offset=max(int((query.get("offset") or ["0"])[0]),0)
        except (TypeError,ValueError):
            return self.j({"error":"invalid message pagination"},400)
        live_hydrated=False
        live_refresh_error=None
        if message_offset == 0 and self.crm_sync is not None:
            try:
                hydration=self.crm_sync.hydrate_recent(fan_id)
                live_hydrated=bool(
                    getattr(hydration,"requested_pages",0)
                )
            except Exception as error:
                logger.exception(
                    "Live CRM hydration failed for fan %s",
                    fan_id,
                )
                live_refresh_error=type(error).__name__
        history_page=message_store.get_history_page(
            fan_id,
            self.creator_id,
            limit=message_limit,
            offset=message_offset,
        )
        history=history_page.messages
        durable_summary=None
        if self.dashboard_repo is not None:
            durable_summary=next(
                (
                    row
                    for row in self.dashboard_repo.conversations(
                        self.creator_id
                    )
                    if row.fan_id==fan_id
                ),
                None,
            )
        sess=(
            self.bot.sessions.get(fan_id)
            if self.bot is not None
            else None
        )
        durable_state=(
            self.bot.state_repo.load_state(self.creator_id,fan_id)
            if self.bot is not None and self.bot.state_repo
            else ConversationStateRepository(self.engine).load_state(
                self.creator_id,
                fan_id,
            )
        )
        style=(
            self.bot._style_profiles.get(fan_id)
            if self.bot is not None
            else None
        )

        # Get PPV sequence progress
        seq_progress = []
        try:
            if self.bot is not None:
                seq_progress = self.bot.sequence_repo.get_fan_progress(fan_id, self.creator_id)
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

        profile=_note(note, purchase) or {
            "fan_id": fan_id,
            "display_name": None,
            "preferences": [],
            "total_spent": (
                purchase.total_spent_millis / 1000
                if purchase is not None
                else 0.0
            ),
            "purchase_count": (
                purchase.purchase_count
                if purchase is not None
                else 0
            ),
            "spend_tier": _spend_tier(
                purchase.total_spent_millis / 1000
                if purchase is not None
                else 0.0
            ),
        }
        if durable_summary is not None:
            if not profile.get("display_name"):
                profile["display_name"]=durable_summary.display_name
            profile["username"]=durable_summary.username
            profile["avatar_url"]=durable_summary.avatar_url
        return self.j({
            "fan_id": fan_id,
            "profile": profile,
            "facts": note.facts if note else [],
            "preferences": note.preferences if note else [],
            "hard_limits": note.hard_limits if note else [],
            "funnel_stage": (
                sess.funnel.current_stage.value
                if sess
                else durable_state.phase
                if durable_state
                else None
            ),
            "sequences": sequences_data,
            "spiral_level": (
                sess.funnel.level.number
                if sess
                else durable_state.escalation_level
                if durable_state
                else 0
            ),
            "spiral_ppvs_bought": (
                sess.funnel.level.ppvs_bought
                if sess
                else durable_state.ppvs_bought
                if durable_state
                else 0
            ),
            "cooldown": (
                sess.funnel.cooldown
                if sess
                else durable_state.cooldown
                if durable_state
                else False
            ),
            "warmup": (
                sess.funnel.is_warmup
                if sess
                else durable_state.warmup
                if durable_state
                else False
            ),
            "style": {
                "formality": style.formality if style else "unknown",
                "avg_length": round(style.avg_length, 1) if style else 0,
                "emoji_rate": round(style.emoji_rate, 2) if style else 0,
                "uses_abbreviations": style.uses_abbreviations if style else False,
                "slang": style.slang if style else [],
            },
            "message_count_stored": history_page.total,
            "message_offset": history_page.offset,
            "message_limit": history_page.limit,
            "has_more_messages": history_page.has_more,
            "history_complete": (
                durable_summary.history_complete
                if durable_summary is not None
                else False
            ),
            "sync_error": (
                durable_summary.sync_error
                if durable_summary is not None
                else None
            ),
            "live_hydrated":live_hydrated,
            "live_refresh_error":live_refresh_error,
            "live_sync_available":self.crm_sync is not None,
            "messages": history,
        })

    def _fans(self):
        purchases = self._purchase_totals()
        return self.j({"fans":[
            _note(n, purchases.get(n.fan_id))
            for n in self._list_notes()
        ],"purchase_source":"attributed_provider_events"})

    def _kpi(self):
        repository = self.dashboard_repo
        if repository is None:
            return self.j(
                {"error":"durable metrics store unavailable"},
                503,
            )
        metrics = repository.metrics(self.creator_id)
        return self.j({
            "source":"durable_attributed_events",
            "known_fans":metrics.known_fans,
            "completed_inbounds":metrics.completed_inbounds,
            "sent_outbounds":metrics.sent_outbounds,
            "text_sends":metrics.text_sends,
            "media_sends":metrics.media_sends,
            "ppv_sends":metrics.ppv_sends,
            "blocked_ppv_intents":metrics.blocked_ppv_intents,
            "delivery_unknown":metrics.delivery_unknown,
            "attributed_purchases":metrics.attributed_purchases,
            "attributed_revenue":metrics.attributed_revenue_millis/1000,
            "aov":(
                metrics.average_order_value_millis/1000
                if metrics.average_order_value_millis is not None
                else None
            ),
            "ppv_unlock_rate":metrics.ppv_unlock_rate,
            "response_time_avg":metrics.average_response_seconds,
            "wallet_transaction_count":metrics.wallet_transactions,
            "wallet_latest_balance":(
                metrics.wallet_latest_balance_millis/1000
                if metrics.wallet_latest_balance_millis is not None
                else None
            ),
            "chatting_ratio":None,
            "script_completion_rate":None,
            "health_label":None,
            "unavailable_metrics":{
                "chatting_ratio":"subscription revenue is not attributed by the current Fansly contract",
                "script_completion_rate":"script execution is not durably tracked",
                "health_label":"the previous label depended on unavailable subscription revenue",
            },
        })

    def _scrs(self):
        inventory = {
            template.name: {
                **_script(template),
                "id":None,
                "origin":"builtin",
                "is_active":True,
                "editable":True,
            }
            for template in BUILTIN_SCRIPTS
        }
        if self.script_repo is not None:
            try:
                for stored in self.script_repo.list_scripts():
                    inventory[stored.template.name] = {
                        **stored.as_json(),
                        "message_count":len(stored.template.messages),
                        "origin":"custom",
                        "editable":True,
                    }
            except Exception as e:
                logger.exception("Failed to list editable scripts")
                return self.j({"error":str(e)},500)
        return self.j({
            "scripts":sorted(
                inventory.values(),
                key=lambda item:(item["category"],item["name"]),
            ),
            "categories":[category.value for category in ScriptCategory],
            "editing_available":self.script_repo is not None,
            "storage":"durable_creator_overrides",
        })

    @staticmethod
    def _script_variables(
        messages: list[str],
        supplied,
    ) -> list[ScriptVariable]:
        if supplied is not None:
            if not isinstance(supplied,list):
                raise ValueError("variables must be an array")
            return [ScriptVariable(**value) for value in supplied]
        names = []
        for message in messages:
            for name in re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}",message):
                if name not in names:
                    names.append(name)
        source_defaults = {
            "fan_name":"fan_notes.display_name",
            "fan_preference":"fan_notes.preferences.0",
            "content_detail":"custom.content_type",
        }
        return [
            ScriptVariable(
                name=name,
                source=source_defaults.get(name,f"custom.{name}"),
                fallback="friend" if name=="fan_name" else "",
            )
            for name in names
        ]

    def _script_from_body(self, body) -> tuple[ScriptTemplate,bool]:
        data=json.loads(body or "{}")
        if not isinstance(data,dict):
            raise ValueError("request body must be an object")
        name=data.get("name","")
        if not isinstance(name,str) or not SCRIPT_NAME_PATTERN.fullmatch(name):
            raise ValueError(
                "name must be 1-100 letters, numbers, hyphens, or underscores"
            )
        messages=data.get("messages",[])
        if (
            not isinstance(messages,list)
            or not 1<=len(messages)<=20
            or any(
                not isinstance(message,str)
                or not message.strip()
                or len(message)>2000
                for message in messages
            )
        ):
            raise ValueError(
                "messages must contain 1-20 non-empty strings"
            )
        description=data.get("description","")
        if not isinstance(description,str) or len(description)>1000:
            raise ValueError("description must be at most 1000 characters")
        conditions=data.get("conditions",{})
        if not isinstance(conditions,dict):
            raise ValueError("conditions must be an object")
        is_active=data.get("is_active",True)
        if not isinstance(is_active,bool):
            raise ValueError("is_active must be a boolean")
        template=ScriptTemplate(
            name=name,
            category=ScriptCategory(data.get("category","welcome")),
            description=description,
            messages=[message.strip() for message in messages],
            variables=self._script_variables(
                messages,
                data.get("variables"),
            ),
            conditions=conditions,
        )
        return template,is_active

    def _script_save(self, body, script_id_str=None):
        if self.script_repo is None:
            return self.j({"error":"script storage is unavailable"},503)
        try:
            script_id=int(script_id_str) if script_id_str else None
            template,is_active=self._script_from_body(body)
            saved=self.script_repo.save(
                template,
                script_id=script_id,
                is_active=is_active,
            )
            if self.bot is not None and hasattr(self.bot,"reload_scripts"):
                self.bot.reload_scripts()
            return self.j({
                "status":"ok",
                "script":saved.as_json(),
                "runtime_applied":self.bot is not None,
            })
        except LookupError as e:
            return self.j({"error":str(e)},404)
        except (
            ValueError,
            TypeError,
            KeyError,
            json.JSONDecodeError,
        ) as e:
            return self.j({"error":str(e)},400)
        except Exception as e:
            logger.exception("Failed to save script")
            return self.j({"error":str(e)},500)

    def _script_delete(self, script_id_str):
        if self.script_repo is None:
            return self.j({"error":"script storage is unavailable"},503)
        try:
            if not self.script_repo.delete(int(script_id_str)):
                return self.j({"error":"not found"},404)
            if self.bot is not None and hasattr(self.bot,"reload_scripts"):
                self.bot.reload_scripts()
            return self.j({
                "status":"ok",
                "runtime_applied":self.bot is not None,
            })
        except ValueError:
            return self.j({"error":"invalid script id"},400)
        except Exception as e:
            logger.exception("Failed to delete script")
            return self.j({"error":str(e)},500)

    def _media_assets(self,q):
        if self.media_repo is None:
            return self.j({
                "assets":[],
                "editing_available":False,
                "provider_listing_supported":False,
                "reason":"media registry storage is unavailable",
            })
        query=(q.get("query",[""])or[""])[0]
        media_type=(q.get("type",[""])or[""])[0]
        try:
            assets=self.media_repo.list_assets(
                query=query,
                media_type=media_type,
            )
            return self.j({
                "assets":[asset.as_json() for asset in assets],
                "editing_available":True,
                "provider_listing_supported":bool(
                    self.client is not None
                    and self.client.capabilities.supports_vault_albums
                    is True
                ),
                "reason":(
                    "Browse connected Fansly vault albums or use this "
                    "registry for labeled, searchable media."
                    if self.client is not None
                    and self.client.capabilities.supports_vault_albums
                    is True
                    else
                    "The configured provider cannot list the Fansly vault. "
                    "This registry contains explicitly registered media."
                ),
            })
        except Exception as e:
            logger.exception("Failed to list media registry")
            return self.j({"error":str(e),"assets":[]},500)

    @staticmethod
    def _optional_https_url(value,field):
        if value in {None,""}:
            return None
        if not isinstance(value,str) or len(value)>4000:
            raise ValueError(f"{field} is invalid")
        parsed=urlsplit(value)
        if (
            parsed.scheme!="https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError(f"{field} must be an HTTPS URL")
        return value

    def _media_asset_save(self,body):
        if self.media_repo is None:
            return self.j({"error":"media registry is unavailable"},503)
        try:
            data=json.loads(body or "{}")
            if not isinstance(data,dict):
                raise ValueError("request body must be an object")
            provider_id=data.get("provider_media_id","")
            if (
                not isinstance(provider_id,str)
                or not PROVIDER_MEDIA_ID_PATTERN.fullmatch(provider_id)
            ):
                raise ValueError(
                    "provider_media_id must be a valid provider media ID"
                )
            title=data.get("title","")
            if not isinstance(title,str) or not title.strip() or len(title)>255:
                raise ValueError("title is required and must be at most 255 characters")
            media_type=data.get("media_type","video")
            if media_type not in {"video","image","gif","audio","other"}:
                raise ValueError("invalid media_type")
            tags=data.get("tags",[])
            if (
                not isinstance(tags,list)
                or len(tags)>20
                or any(
                    not isinstance(tag,str)
                    or not tag.strip()
                    or len(tag)>40
                    for tag in tags
                )
            ):
                raise ValueError("tags must contain at most 20 short strings")
            account_media_id=data.get("account_media_id")
            if account_media_id not in {None,""} and (
                not isinstance(account_media_id,str)
                or not account_media_id.isdigit()
                or len(account_media_id)>128
            ):
                raise ValueError("account_media_id must be numeric")
            asset=MediaAsset(
                id=None,
                creator_id=self.creator_id,
                provider_media_id=provider_id,
                account_media_id=account_media_id or None,
                title=title.strip(),
                file_name=(
                    data.get("file_name")
                    if isinstance(data.get("file_name"),str)
                    else None
                ),
                media_type=media_type,
                mime_type=(
                    data.get("mime_type")
                    if isinstance(data.get("mime_type"),str)
                    else None
                ),
                thumbnail_url=self._optional_https_url(
                    data.get("thumbnail_url"),
                    "thumbnail_url",
                ),
                preview_url=self._optional_https_url(
                    data.get("preview_url"),
                    "preview_url",
                ),
                tags=tuple(dict.fromkeys(tag.strip() for tag in tags)),
                source="manual",
                status="ready",
            )
            saved=self.media_repo.save(asset)
            return self.j({"status":"ok","asset":saved.as_json()})
        except (
            ValueError,
            TypeError,
            KeyError,
            json.JSONDecodeError,
        ) as e:
            return self.j({"error":str(e)},400)
        except Exception as e:
            logger.exception("Failed to save media asset")
            return self.j({"error":str(e)},500)

    def _media_asset_delete(self,asset_id_str):
        if self.media_repo is None:
            return self.j({"error":"media registry is unavailable"},503)
        try:
            if not self.media_repo.delete(int(asset_id_str)):
                return self.j({"error":"not found"},404)
            return self.j({"status":"ok"})
        except ValueError:
            return self.j({"error":"invalid media asset id"},400)
        except Exception as e:
            logger.exception("Failed to delete media asset")
            return self.j({"error":str(e)},500)

    def _conn(self,test):
        if not self.client:
            return self.j({
                "connected":False,
                "account_id":"",
                "status":"unavailable",
                "live_checked":False,
                "error":self.server.provider_error
                or "provider client is not initialized",
            })
        ok=bool(self.server.provider_connected)
        err=self.server.provider_error
        if test:
            try:
                self.client.verify_auth()
                ok=True
                err=None
            except Exception as e:
                ok=False
                err=str(e)[:200]
            self.server.provider_connected=ok
            self.server.provider_error=err
            self.server.provider_last_checked_at=datetime.now(
                timezone.utc
            )
        account_id=""
        if ok:
            try:
                resolved=self.client.account_id
                account_id=(
                    resolved[:12]+"..."
                    if resolved and len(resolved)>12
                    else resolved or ""
                )
            except Exception as e:
                ok=False
                err=str(e)[:200]
                self.server.provider_connected=False
                self.server.provider_error=err
        return self.j({
            "connected":ok,
            "account_id":account_id,
            "status":(
                "live_verified"
                if ok
                and self.server.provider_last_checked_at is not None
                else "startup_verified"
                if ok
                else "offline"
            ),
            "live_checked":bool(
                self.server.provider_last_checked_at is not None
            ),
            "last_checked_at":(
                self.server.provider_last_checked_at.isoformat()
                if self.server.provider_last_checked_at
                else None
            ),
            "provider":(
                self.client.provider_name
                if self.client is not None
                and isinstance(
                    getattr(self.client, "provider_name", None),
                    str,
                )
                else "Fansly provider"
            ),
            "error":err,
        })

    def _ai_settings_get(self):
        if self.ai_settings is None:
            return self.j(
                {"error": "DeepSeek settings are unavailable"},
                503,
            )
        return self.j(self.ai_settings.status())

    def _ai_settings_save(self, body: str):
        if self.ai_settings is None:
            return self.j(
                {"error": "DeepSeek settings are unavailable"},
                503,
            )
        try:
            data = json.loads(body) if body else {}
            if not isinstance(data, dict):
                return self.j(
                    {"error": "request body must be an object"},
                    400,
                )
            api_key = data.get("api_key") if "api_key" in data else None
            model = data.get("model")
            if api_key is not None and not isinstance(api_key, str):
                return self.j({"error": "api_key must be a string"}, 400)
            if model is not None and not isinstance(model, str):
                return self.j({"error": "model must be a string"}, 400)
            result = self.ai_settings.save(
                api_key=api_key,
                model=model,
            )
            return self.j(result)
        except json.JSONDecodeError:
            return self.j({"error": "invalid JSON payload"}, 400)
        except Exception as error:
            from ..settings.ai import AISettingsError

            if isinstance(error, AISettingsError):
                return self.j({"error": str(error)}, 400)
            logger.exception("Failed to save DeepSeek settings")
            return self.j(
                {"error": "DeepSeek settings could not be saved"},
                500,
            )

    def _ai_connection_test(self):
        if self.ai_settings is None:
            return self.j(
                {"error": "DeepSeek settings are unavailable"},
                503,
            )
        try:
            return self.j(self.ai_settings.test_connection())
        except Exception as error:
            from ..settings.ai import AISettingsError

            if isinstance(error, AISettingsError):
                return self.j({"error": str(error)}, 400)
            logger.exception("DeepSeek connection test failed")
            return self.j(
                {"error": "DeepSeek connection test failed"},
                500,
            )

    def _bot_status(self):
        if not self.bot:
            return self.j({
                "available":False,
                "enabled":False,
                "persisted_enabled":False,
                "consistent":True,
                "reason":self.server.provider_error
                or "bot is not initialized",
                "controlled_launch":False,
                "launch_ready":False,
                "allowed_fan_count":0,
                "mode":"unavailable",
                "unread_replies":False,
                "online_outreach":False,
            })
        enabled=bool(self.bot.enabled)
        persisted=None
        if self.engine is not None:
            try:
                from ..settings.store import SettingsStore
                raw=SettingsStore(
                    engine=self.engine,
                    creator_id=self.creator_id,
                ).get("bot_enabled")
                if raw is not None:
                    persisted=raw.lower()=="true"
            except Exception:
                logger.exception("Failed to read persisted bot state")
        return self.j({
            "available":True,
            "enabled":enabled,
            "persisted_enabled":persisted,
            "consistent":(
                persisted is None or persisted==enabled
            ),
            "reason":None,
            "controlled_launch":bool(
                getattr(self.bot, "require_fan_allowlist", False)
            ),
            "launch_ready":bool(
                getattr(self.bot, "launch_ready", True)
            ),
            "allowed_fan_count":len(
                getattr(self.bot, "allowed_fan_ids", ())
            ),
            "mode":getattr(
                getattr(self.bot, "bot_mode", None),
                "value",
                "full_ppv",
            ),
            "unread_replies":bool(
                getattr(self.bot, "enable_unread_replies", True)
            ),
            "online_outreach":bool(
                getattr(self.bot, "enable_online_outreach", False)
            ),
            "launch_block_reason":getattr(
                self.bot,
                "launch_block_reason",
                None,
            ),
        })

    def _operations(self):
        pipeline_counts = {}
        crm_sync = {}
        if self.engine is not None:
            try:
                pipeline_counts = MessageProcessingRepository(
                    self.engine
                ).counts(self.creator_id)
            except Exception:
                logger.exception("Failed to load pipeline counts")
            try:
                crm_sync = CrmSyncRepository(
                    self.engine
                ).summary(self.creator_id)
            except Exception:
                logger.exception("Failed to load CRM sync status")
        runtime = (
            self.server.runtime_monitor.snapshot()
            if self.server.runtime_monitor is not None
            else {}
        )
        return self.j({
            "runtime":runtime,
            "database_ready":self._database_ready(),
            "provider":{
                "connected":bool(self.server.provider_connected),
                "blocked":bool(self.server.provider_error),
            },
            "bot":{
                "available":self.bot is not None,
                "enabled":bool(self.bot and self.bot.enabled),
                "controlled_launch":bool(
                    self.bot
                    and getattr(
                        self.bot,
                        "require_fan_allowlist",
                        False,
                    )
                ),
                "launch_ready":bool(
                    self.bot
                    and getattr(self.bot, "launch_ready", True)
                ),
                "allowed_fan_count":len(
                    getattr(self.bot, "allowed_fan_ids", ())
                ) if self.bot else 0,
            },
            "pipeline":pipeline_counts,
            "crm_sync":crm_sync,
        })

    def _pers_get(self,q):
        cid = (q.get("creator",[None])or[None])[0] or self.creator_id
        if not CREATOR_ID_PATTERN.fullmatch(cid):
            return self.j({"error": "invalid creator id"}, 400)
        p = Path(self.server.persona_dir)/f"{cid}.yaml"
        raw=p.read_text(encoding="utf-8") if p.exists() else ""
        parsed={}
        if raw:
            try:
                parsed=yaml.safe_load(raw) or {}
            except Exception:
                parsed={}
        if isinstance(parsed,dict):
            parsed.pop("creator_id",None)
        else:
            parsed={}
        return self.j({
            "creator_id":cid,
            "yaml":raw,
            "persona":parsed,
            "runtime_applied":bool(
                self.bot is not None
                and cid==self.bot.creator_id
            ),
        })

    def _pers_post(self,q,b):
        cid = (q.get("creator",[None])or[None])[0] or self.creator_id
        if not CREATOR_ID_PATTERN.fullmatch(cid):
            return self.j({"error": "invalid creator id"}, 400)
        try:
            data=yaml.safe_load(b)
            if not isinstance(data,dict):
                raise ValueError("persona YAML must contain an object")
            PersonaDocument(**{**data,"creator_id":cid})
        except Exception as e:
            return self.j({"error":str(e)},400)
        directory=Path(self.server.persona_dir)
        directory.mkdir(parents=True,exist_ok=True)
        target=directory/f"{cid}.yaml"
        temporary=directory/f".{cid}.yaml.tmp"
        try:
            temporary.write_text(b,encoding="utf-8")
            os.replace(temporary,target)
        finally:
            if temporary.exists():
                temporary.unlink()
        applied=False
        if self.bot is not None and cid==self.bot.creator_id:
            try:
                self.bot.reload_persona()
                applied=True
            except Exception as e:
                logger.exception("Failed to apply saved persona")
                return self.j({
                    "error":f"saved but runtime reload failed: {e}",
                    "saved":True,
                    "runtime_applied":False,
                },500)
        return self.j({
            "status":"ok",
            "saved":True,
            "runtime_applied":applied,
        })

    def _chat_guidance(self):
        service = self.server.chat_guidance
        if service is None:
            self.j(
                {"error": "chat guidance settings are unavailable"},
                503,
            )
            return None
        return service

    def _chat_instructions_get(self):
        service = self._chat_guidance()
        if service is None:
            return
        content = service.snapshot().chat_instructions
        return self.j({
            "content":content,
            "creator_id":self.creator_id,
            "storage":"database",
            "runtime_applied":True,
            "purpose":"live conversation instructions",
        })

    def _chat_instructions_post(self,b):
        service = self._chat_guidance()
        if service is None:
            return
        try:
            snapshot = service.save_chat_instructions(b)
        except ChatGuidanceError as error:
            return self.j({"error":str(error)},400)
        return self.j({
            "status":"ok",
            "saved":True,
            "runtime_applied":True,
            "storage":"database",
            "characters":len(snapshot.chat_instructions),
        })

    def _bible_get(self):
        service = self._chat_guidance()
        if service is None:
            return
        content = service.snapshot().brand_bible
        return self.j({
            "content":content,
            "creator_id":self.creator_id,
            "storage":"database",
            "runtime_applied":True,
            "purpose":"live brand instructions",
        })

    def _bible_post(self,b):
        service = self._chat_guidance()
        if service is None:
            return
        try:
            snapshot = service.save_brand_bible(b)
        except ChatGuidanceError as error:
            return self.j({"error":str(error)},400)
        return self.j({
            "status":"ok",
            "saved":True,
            "runtime_applied":True,
            "storage":"database",
            "characters":len(snapshot.brand_bible),
        })

    # ─── PPV SEQUENCES ──────────────────────────────────

    def _paid_messages_supported(self) -> bool:
        if self.client is None:
            return False
        return (
            self.client.capabilities.supports_paid_messages
            is True
        )

    @staticmethod
    def _paid_messages_reason() -> str:
        return (
            "The configured provider does not support paid/paywalled messages"
        )

    def _sequence_from_body(self, body, existing=None):
        data=json.loads(body)
        if not isinstance(data,dict):
            raise ValueError("request body must be an object")
        name=data.get("name",existing.name if existing else "")
        if not isinstance(name,str) or not name.strip():
            raise ValueError("sequence name is required")
        if len(name.strip())>100:
            raise ValueError("sequence name is too long")
        trigger=SequenceTrigger(
            data.get(
                "trigger",
                existing.trigger.value if existing else "welcome",
            )
        )
        funnel_stage=data.get(
            "funnel_stage",
            existing.funnel_stage if existing else "rapport",
        )
        if funnel_stage not in {
            "rapport",
            "tease",
            "offer",
            "handle",
            "close",
        }:
            raise ValueError("invalid funnel stage")
        is_active=data.get(
            "is_active",
            existing.is_active if existing else False,
        )
        if not isinstance(is_active,bool):
            raise ValueError("is_active must be a boolean")
        if is_active and not self._paid_messages_supported():
            raise PermissionError(self._paid_messages_reason())
        raw_steps=data.get(
            "steps",
            existing.steps if existing else [],
        )
        if not isinstance(raw_steps,list):
            raise ValueError("steps must be an array")
        steps=[]
        for position,raw in enumerate(raw_steps,start=1):
            if isinstance(raw,SequenceStep):
                media_id=raw.media_id
                preview_id=raw.preview_id
                price=raw.price
                tease=raw.tease_script
                offer=raw.offer_script
            else:
                if not isinstance(raw,dict):
                    raise ValueError(
                        f"step {position} must be an object"
                    )
                media_id=raw.get("media_id","")
                preview_id=raw.get("preview_id")
                price=raw.get("price")
                tease=raw.get("tease_script","")
                offer=raw.get("offer_script","")
            if (
                not isinstance(media_id,str)
                or not PROVIDER_MEDIA_ID_PATTERN.fullmatch(media_id)
            ):
                raise ValueError(
                    f"step {position} requires a valid provider media ID"
                )
            if preview_id not in {None,""}:
                if (
                    not isinstance(preview_id,str)
                    or not PROVIDER_MEDIA_ID_PATTERN.fullmatch(preview_id)
                ):
                    raise ValueError(
                        f"step {position} has an invalid preview media ID"
                    )
            if (
                isinstance(price,bool)
                or not isinstance(price,(int,float))
                or not math.isfinite(float(price))
                or float(price)<=0
            ):
                raise ValueError(
                    f"step {position} requires a positive price"
                )
            if not isinstance(tease,str) or not isinstance(offer,str):
                raise ValueError("sequence scripts must be text")
            step=SequenceStep(
                sequence_id=existing.id if existing else 0,
                position=position,
                media_id=media_id,
                preview_id=preview_id or None,
                price=float(price),
                tease_script=tease,
                offer_script=offer,
            )
            steps.append(step)
        return Sequence(
            id=existing.id if existing else None,
            name=name.strip(),
            trigger=trigger,
            funnel_stage=funnel_stage,
            is_active=is_active,
            created_at=(
                existing.created_at
                if existing
                else datetime.now(timezone.utc)
            ),
            steps=steps,
        )

    def _seq_list(self):
        if not self.bot:
            return self.j({
                "editing_available":False,
                "paid_messages_supported":False,
                "blocked_reason":(
                    self.server.provider_error
                    or "bot is not initialized"
                ),
                "sequences":[],
            })
        try:
            seqs = self.bot.sequence_repo.list_sequences()
            supported=self._paid_messages_supported()
            return self.j({
                "editing_available":True,
                "paid_messages_supported":supported,
                "blocked_reason":(
                    None
                    if supported
                    else self._paid_messages_reason()
                ),
                "sequences":[
                {"id":s.id,"name":s.name,"trigger":s.trigger.value,"funnel_stage":s.funnel_stage,
                 "is_active":s.is_active,"step_count":s.step_count(),"total_price":round(s.total_price(),2),
                 "effective_active":bool(s.is_active and supported),
                 "blocked_reason":(
                     self._paid_messages_reason()
                     if s.is_active and not supported
                     else None
                 ),
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
            supported=self._paid_messages_supported()
            return self.j({
                "id":s.id,"name":s.name,"trigger":s.trigger.value,"funnel_stage":s.funnel_stage,
                "is_active":s.is_active,"step_count":s.step_count(),"total_price":round(s.total_price(),2),
                "paid_messages_supported":supported,
                "effective_active":bool(s.is_active and supported),
                "blocked_reason":(
                    self._paid_messages_reason()
                    if not supported
                    else None
                ),
                "created_at":str(s.created_at),
                "steps":[{"id":st.id,"position":st.position,"media_id":st.media_id,"preview_id":st.preview_id,
                          "price":st.price,"tease_script":st.tease_script,"offer_script":st.offer_script}
                         for st in s.steps]
            })
        except ValueError as e:
            return self.j({"error":str(e)},400)
        except Exception as e:
            return self.j({"error":str(e)},500)

    def _seq_create(self, body):
        if not self.bot: return self.j({"error":"no bot"},503)
        try:
            s=self._sequence_from_body(body)
            saved=self.bot.sequence_repo.save_sequence_with_steps(s)
            return self.j({"status":"ok","id":saved.id})
        except PermissionError as e:
            return self.j({"error":str(e)},409)
        except (ValueError,KeyError,json.JSONDecodeError) as e:
            return self.j({"error":str(e)},400)
        except Exception as e:
            logger.exception("Failed to create sequence")
            return self.j({"error":str(e)},500)

    def _seq_update(self, seq_id_str, body):
        if not self.bot: return self.j({"error":"no bot"},503)
        try:
            s = self.bot.sequence_repo.get_sequence(int(seq_id_str))
            if not s: return self.j({"error":"not found"},404)
            updated=self._sequence_from_body(body,s)
            self.bot.sequence_repo.save_sequence_with_steps(updated)
            return self.j({"status":"ok"})
        except PermissionError as e:
            return self.j({"error":str(e)},409)
        except (ValueError,KeyError,json.JSONDecodeError) as e:
            return self.j({"error":str(e)},400)
        except Exception as e:
            logger.exception("Failed to update sequence")
            return self.j({"error":str(e)},500)

    def _seq_delete(self, seq_id_str):
        if not self.bot: return self.j({"error":"no bot"},503)
        try:
            deleted=self.bot.sequence_repo.delete_sequence(
                int(seq_id_str)
            )
            if not deleted:
                return self.j({"error":"not found"},404)
            return self.j({"status":"ok"})
        except ValueError as e:
            return self.j({"error":str(e)},400)
        except Exception as e:
            return self.j({"error":str(e)},500)

    # ─── VAULT ALBUMS (Fansly API) ─────────────────────

    def _vault(self):
        return self.j({
            "files":_list_vault(self.vault_dir),
            "dir":self.vault_dir,
            "provider_ready":False,
            "reason":(
                "Local files are not provider media. Upload them first or "
                "select existing Fansly vault media."
            ),
        })

    def _vault_albums(self):
        if not self.client:
            return self.j({
                "supported":False,
                "albums":[],
                "reason":"provider client is unavailable",
            })
        if (
            self.client.capabilities.supports_vault_albums
            is not True
        ):
            return self.j({
                "supported":False,
                "albums":[],
                "reason":(
                    "The configured provider cannot browse vault albums"
                ),
            })
        try:
            albums = self.client.list_albums()
            return self.j({"supported":True,"albums":[
                {"id":a.get("id") or a.get("albumId"),"name":a.get("name") or a.get("label","Album")}
                for a in albums
            ]})
        except Exception as e:
            return self.j({
                "supported":False,
                "error":str(e),
                "albums":[],
            })

    def _vault_album_media(self, album_id):
        if (
            not self.client
            or self.client.capabilities.supports_vault_albums
            is not True
        ):
            return self.j({
                "supported":False,
                "media":[],
                "reason":(
                    "The configured provider cannot browse vault album media"
                ),
            })
        try:
            media=[]
            cursor=None
            seen_cursors=set()
            for _ in range(20):
                page,next_cursor=self.client.get_album_media(
                    album_id,
                    cursor=cursor,
                )
                if isinstance(page,list):
                    media.extend(page)
                if not next_cursor:
                    break
                if next_cursor in seen_cursors:
                    raise RuntimeError(
                        "provider repeated the vault media cursor"
                    )
                seen_cursors.add(next_cursor)
                cursor=next_cursor
            if isinstance(media,list):
                result=[]
                for m in media:
                    details=m.get("media",{}) if isinstance(m,dict) else {}
                    media_id=m.get("mediaId") or details.get("id") or m.get("id")
                    numeric_type=details.get("type",m.get("type"))
                    media_type=(
                        "image" if numeric_type==1
                        else "video" if numeric_type==2
                        else str(numeric_type or "unknown")
                    )
                    locations=details.get("locations",[])
                    preview_url=(
                        locations[0].get("location")
                        if locations and isinstance(locations[0],dict)
                        else None
                    )
                    result.append({
                        "id":media_id,
                        "accountMediaId":m.get("id"),
                        "mediaId":media_id,
                        "type":media_type,
                        "label":(
                            m.get("label")
                            or m.get("description")
                            or details.get("filename")
                            or str(media_id or "")
                        ),
                        "previewId":m.get("previewId"),
                        "previewUrl":preview_url,
                    })
                return self.j({"supported":True,"media":result})
            return self.j({"supported":True,"media":[]})
        except Exception as e:
            return self.j({
                "supported":False,
                "error":str(e),
                "media":[],
            })

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
        old_state=bool(self.bot.enabled)
        persisted=False
        try:
            data = json.loads(body) if body else {}
            if not isinstance(data,dict):
                return self.j({"error":"request body must be an object"},400)
            if "enabled" in data and not isinstance(
                data["enabled"],
                bool,
            ):
                return self.j({"error":"enabled must be a boolean"},400)
            target = (
                data["enabled"]
                if "enabled" in data
                else not old_state
            )
            from ..settings.store import SettingsStore
            store = SettingsStore(
                engine=self.engine,
                creator_id=self.creator_id,
            )
            store.set("bot_enabled", str(target).lower())
            persisted=True
            new_state = self.bot.toggle(force=target)
            if bool(new_state) != target:
                raise RuntimeError("bot rejected the requested state")
            return self.j({
                "available":True,
                "enabled":bool(new_state),
                "persisted_enabled":target,
                "consistent":True,
            })
        except Exception as e:
            if persisted:
                try:
                    store.set(
                        "bot_enabled",
                        str(old_state).lower(),
                    )
                except Exception:
                    logger.exception(
                        "Failed to roll back persisted bot state"
                    )
            if bool(self.bot.enabled) != old_state:
                try:
                    self.bot.toggle(force=old_state)
                except Exception:
                    logger.exception(
                        "Failed to roll back in-memory bot state"
                    )
            from ..bot import LaunchGuardError
            status = 409 if isinstance(e, LaunchGuardError) else 500
            return self.j({"error": str(e)}, status)

    def log_message(self,*a): pass

class DashboardServer:
    def __init__(
        self,
        bot,
        port=8080,
        vault_dir="/data/videos",
        engine=None,
        client=None,
        creator_id: Optional[str] = None,
        provider_connected: Optional[bool] = None,
        provider_error: Optional[str] = None,
        persona_dir: Optional[str] = None,
        brand_bible_path: Optional[str] = None,
        dashboard_user: Optional[str] = None,
        dashboard_password: Optional[str] = None,
        allowed_hosts: Optional[set[str]] = None,
        csrf_token: Optional[str] = None,
        apifansly_webhook_token: Optional[str] = None,
        runtime_monitor=None,
        crm_sync=None,
        ai_settings=None,
        chat_guidance=None,
    ):
        hosts = {"localhost", "127.0.0.1", "::1"}
        if allowed_hosts is None:
            configured = os.getenv("DASHBOARD_ALLOWED_HOSTS", "")
            hosts.update(
                host.strip().lower()
                for host in configured.split(",")
                if host.strip()
            )
            for env_name in ("RAILWAY_PUBLIC_DOMAIN", "RAILWAY_PRIVATE_DOMAIN"):
                value = os.getenv(env_name, "").strip().lower()
                if value:
                    hosts.add(value)
        else:
            hosts.update(host.strip().lower() for host in allowed_hosts if host.strip())

        self.server = ThreadingHTTPServer(("0.0.0.0",port),DashboardHandler)
        self.server.daemon_threads = True
        self.server.bot = bot
        self.server.vault_dir = vault_dir
        self.server.engine = engine or (
            bot.note_repo.engine if bot is not None else None
        )
        self.server.client = client or (
            bot.client if bot is not None else None
        )
        self.server.creator_id = creator_id or (
            bot.creator_id if bot is not None else "sunny_charm"
        )
        self.server.provider_connected = (
            bool(bot is not None)
            if provider_connected is None
            else bool(provider_connected)
        )
        self.server.provider_error = provider_error
        self.server.provider_last_checked_at = None
        self.server.runtime_monitor = runtime_monitor
        self.server.crm_sync = crm_sync
        self.server.ai_settings = ai_settings
        self.server.chat_guidance = chat_guidance
        self.server.persona_dir = persona_dir or (
            bot.persona_loader.config_dir
            if bot is not None and hasattr(bot, "persona_loader")
            else PERSONA_DIR
        )
        self.server.brand_bible_path = (
            brand_bible_path or BRAND_BIBLE_PATH
        )
        self.server.dashboard_user = (
            os.getenv("DASHBOARD_USER", "")
            if dashboard_user is None
            else dashboard_user
        )
        self.server.dashboard_password = (
            os.getenv("DASHBOARD_PASSWORD", "")
            if dashboard_password is None
            else dashboard_password
        )
        self.server.allowed_hosts = hosts
        self.server.csrf_token = csrf_token or secrets.token_urlsafe(32)
        self.server.apifansly_webhook_token = (
            os.getenv("APIFANSLY_WEBHOOK_TOKEN", "")
            if apifansly_webhook_token is None
            else apifansly_webhook_token
        ).strip()
        self.server.script_repo = (
            ScriptTemplateRepository(
                self.server.engine,
                self.server.creator_id,
            )
            if self.server.engine is not None
            else None
        )
        self.server.media_repo = (
            MediaAssetRepository(
                self.server.engine,
                self.server.creator_id,
            )
            if self.server.engine is not None
            else None
        )
        self.csrf_token = self.server.csrf_token
    def handle_request(self): self.server.handle_request()
    def shutdown(self): self.server.shutdown()
