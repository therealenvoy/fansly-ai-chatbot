"""
Dashboard web server — SPA + REST API for the Fansly AI bot.
Sidebar navigation, Linear-dark aesthetic, proper UX hierarchy per section.
"""
import base64
import binascii
import hmac
import json
import logging
import os
import re
import secrets

import yaml
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Optional, TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

from ..sequences.models import Sequence, SequenceTrigger, SequenceStep, FanSequenceProgress, StepStatus

logger = logging.getLogger("fansly-bot.dashboard")
if TYPE_CHECKING:
    from ..bot import FanslyBot

PERSONA_DIR = "/data/config/creators"
BRAND_BIBLE_PATH = "/data/config/brand_bible.md"
MAX_BODY_BYTES = 1024 * 1024
CREATOR_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


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
  var subtitles={'funnel':'Live conversations and buying stages','vault':'Media ready for offers','fans':'Audience memory and value','scripts':'Reusable conversation playbooks','kpis':'The numbers that drive revenue','sequences':'Automated PPV journeys','settings':'Connections, voice, and brand rules'};
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
  var r=await fetch('/api/bot/status');
  var d=await r.json();
  updateToggleUI(d.enabled);
}
function updateToggleUI(enabled){
  var dot=document.getElementById('dot');
  var label=document.getElementById('toggle-label');
  var button=document.getElementById('bot-toggle');
  if(!dot||!label)return;
  dot.className='dot'+(enabled?'':' off');
  label.textContent=enabled?'Bot on':'Bot off';
  label.style.color=enabled?'var(--green)':'var(--red)';
  if(button){button.setAttribute('aria-pressed',enabled?'true':'false');button.setAttribute('aria-label',enabled?'Turn bot off':'Turn bot on')}
}
async function toggleBot(){
  var r=await M('/api/bot/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  var d=await r.json();
  updateToggleUI(d.enabled);
}

function loadVault(){
  var c=document.getElementById('content');
  F('/api/vault').then(function(d){
    if(!d||!d.files||!d.files.length){c.innerHTML=emptyState('&#9633;','Your vault is empty','Upload media to /data/videos. Files added there become available for offers and sequences.');return}
    var h='<div class="media-grid">';d.files.forEach(function(f){var i=f.type==='video'?'&#127916;':f.type==='image'?'&#128444;':'&#128196;';h+='<div class="media-card"><div class="ico">'+i+'</div><div class="name">'+esc(f.name)+'</div><div class="size">'+esc(f.size)+'</div></div>'});h+='</div>';c.innerHTML=h;
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
    var cards=[{l:'Chatting Ratio',v:(d.chatting_ratio||0).toFixed(1)+':1',c:d.chatting_ratio>=6?'up':d.chatting_ratio>=4?'warn':'bad'},{l:'PPV Unlock Rate',v:(d.ppv_unlock_rate||0).toFixed(1)+'%',c:d.ppv_unlock_rate>=8?'up':d.ppv_unlock_rate>=5?'warn':'bad'},{l:'Avg Order Value',v:'$'+(d.aov||0).toFixed(0),c:d.aov>=30?'up':'warn'},{l:'Script Completion',v:(d.script_completion_rate||0).toFixed(1)+'%',c:d.script_completion_rate>=18?'up':'warn'},{l:'Health',v:(d.health_label||'N/A').toUpperCase(),c:d.health_label==='elite'||d.health_label==='healthy'?'up':'warn'},{l:'Active Fans',v:d.active_fans||0,c:'up'}];
    c.innerHTML='<div class="cards">'+cards.map(function(card){return'<div class="card"><h3>'+esc(card.l)+'</h3><div class="v '+attr(card.c)+'\">'+esc(card.v)+'</div></div>'}).join('')+'</div>';
  });
}

function loadSettings(){
  var c=document.getElementById('content');
  var h='<div class="block"><h3>API connection</h3><div class="g3" id="api-status">Loading...</div><div style="margin-top:14px"><button class="btn-ghost" data-action="test-connection">Test connection</button> <span id="conn-result"></span></div></div>';
  h+='<div class="block"><h3>Persona</h3><div class="row"><select id="psel"><option value="sunny_charm">sunny_charm</option></select><button class="btn-ghost" data-action="load-persona">Load</button><span class="done" id="psaved">Saved</span></div><label>config/creators/{model}.yaml</label><textarea id="ped" placeholder="tone: flirty&#10;signature_phrases:&#10;  - hey babe"></textarea><div style="margin-top:10px"><button class="btn" data-action="save-persona">Save Persona</button></div></div>';
  h+='<div class="block"><h3>Brand Bible</h3><label>config/brand_bible.md</label><textarea id="bed" placeholder="# Brand Bible&#10;&#10;## Voice..."></textarea><div style="margin-top:10px"><button class="btn" data-action="save-brand-bible">Save Brand Bible</button> <span class="done" id="bsaved">Saved</span></div></div>';
  c.innerHTML=h;loadConn();loadPersona();loadBrandBible();
}
function loadConn(){F('/api/connection').then(function(d){var el=document.getElementById('api-status');if(!d){el.innerHTML='<div class="card"><h3>Error</h3><div style="font-size:12px;color:#f87171">Failed</div></div>';return}el.innerHTML='<div class="card"><h3>Account</h3><div style="font-size:12px">'+esc(d.account_id)+'</div></div><div class="card"><h3>API</h3><div class="v '+(d.connected?'up':'bad')+'" style="font-size:16px">'+(d.connected?'Connected':'Offline')+'</div></div><div class="card"><h3>Endpoint</h3><div style="font-size:11px;color:var(--tx3)">app.onlyfansapi.com</div></div>'})}
function testConn(){var el=document.getElementById('conn-result');el.textContent='Testing\u2026';el.style.color='var(--tx3)';M('/api/connection/test',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(function(r){return r.json()}).then(function(d){var ok=d&&d.connected;el.textContent=ok?'Connected':'Failed: '+(d.error||'unknown');el.style.color=ok?'var(--green)':'#f87171';loadConn()})}
function loadPersona(){var m=document.getElementById('psel').value;F('/api/persona?creator='+encodeURIComponent(m)).then(function(d){document.getElementById('ped').value=d&&d.yaml||''})}
function savePersona(){var m=document.getElementById('psel').value,y=document.getElementById('ped').value;M('/api/persona?creator='+encodeURIComponent(m),{method:'POST',headers:{'Content-Type':'text/yaml; charset=utf-8'},body:y}).then(function(r){var el=document.getElementById('psaved');if(r.ok){el.style.display='flex';setTimeout(function(){el.style.display='none'},2000)}})}
function loadBrandBible(){F('/api/brand-bible').then(function(d){document.getElementById('bed').value=d&&d.content||''})}
function saveBible(){var c=document.getElementById('bed').value;M('/api/brand-bible',{method:'POST',headers:{'Content-Type':'text/markdown; charset=utf-8'},body:c}).then(function(r){var el=document.getElementById('bsaved');if(r.ok){el.style.display='flex';setTimeout(function(){el.style.display='none'},2000)}})}

// ═══ PPV SEQUENCES ════════════════════════════════════
function loadSequences(){
  var c=document.getElementById('content');
  F('/api/sequences').then(function(d){
    var seqs=d&&d.sequences||[];
    var h=sectionIntro('PPV ladders','Build a clear progression from first offer to highest-value content.','<button class="btn" data-action="new-sequence">New sequence</button>');
    if(!seqs.length){h+=emptyState('&#8644;','No sequences yet','Create a PPV ladder to automate a consistent offer journey for each fan segment.');c.innerHTML=h;return}
    h+='<div class="panel"><table><thead><tr><th>Name</th><th>Trigger</th><th>Steps</th><th>Total</th><th>Active</th><th></th></tr></thead><tbody>';
    seqs.forEach(function(s){var sid=Number(s.id);h+='<tr class="clickable" data-action="edit-sequence" data-sequence-id="'+sid+'"><td style="color:var(--tx)">'+esc(s.name)+'</td><td><span class="badge '+(s.trigger=='whale'?'whale':s.trigger=='re_engage'?'bad':'avg')+'\">'+esc(s.trigger)+'</span></td><td>'+Number(s.step_count||0)+'</td><td>$'+Number(s.total_price||0).toFixed(0)+'</td><td>'+(s.is_active?'<span style="color:var(--green)">&#9679;</span>':'<span style="color:var(--tx3)">&#9679;</span>')+'</td><td><button class="btn-ghost" data-action="delete-sequence" data-sequence-id="'+sid+'">&#128465;</button></td></tr>'});
    h+='</tbody></table></div>';c.innerHTML=h;
  });
}
var editSeqId=null;
var dashboardAlbums=[];
var dashboardSteps=[];
function newSequence(){editSeqId=null;openSeqEditor({name:'',trigger:'welcome',funnel_stage:'rapport',is_active:true,steps:[]})}
function editSeq(id){
  F('/api/sequences/'+id).then(function(d){
    if(!d)return;editSeqId=d.id;openSeqEditor(d);
  });
}
function openSeqEditor(s){
  var c=document.getElementById('content');
  var triggers=['new_sub','welcome','rapport','whale','re_engage','manual'];
  var h='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px"><h3 style="font-size:14px;font-weight:600">'+(editSeqId?'Edit':'New')+' Sequence</h3><div><button class="btn-ghost" data-action="load-sequences" style="margin-right:8px">&#8592; Back</button><button class="btn" data-action="save-sequence">&#128190; Save</button></div></div>';
  h+='<div class="panel" style="padding:18px;margin-bottom:14px"><div class="g3" style="margin-bottom:12px">';
  h+='<div><label>Name</label><input id="sname" value="'+attr(s.name||'')+'" placeholder="e.g. Welcome Ladder"/></div>';
  h+='<div><label>Trigger</label><select id="strigger">'+triggers.map(function(t){return'<option value="'+t+'"'+(s.trigger==t?' selected':'')+'>'+t.replace('_',' ')+'</option>'}).join('')+'</select></div>';
  h+='<div><label>Funnel Stage</label><select id="sfunnel"><option value="rapport"'+(s.funnel_stage=='rapport'?' selected':'')+'>Rapport</option><option value="tease"'+(s.funnel_stage=='tease'?' selected':'')+'>Tease</option><option value="offer"'+(s.funnel_stage=='offer'?' selected':'')+'>Offer</option><option value="close"'+(s.funnel_stage=='close'?' selected':'')+'>Close</option></select></div>';
  h+='<div><label>Active</label><select id="sactive"><option value="1"'+(s.is_active?' selected':'')+'>Yes</option><option value="0"'+(s.is_active?'':' selected')+'>No</option></select></div>';
  h+='</div></div>';
  h+='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px"><h4 style="font-size:12px;font-weight:500;color:var(--tx2)">Steps ('+((s.steps||[]).length)+')</h4><button class="btn-ghost" data-action="add-step">+ Add Step</button></div>';
  h+='<div id="steps-container"></div>';
  c.innerHTML=h;
  F('/api/vault-albums').then(function(d){
    dashboardAlbums=d&&d.albums||[];
    if(typeof renderSteps=='function')renderSteps(s.steps||[]);
    else setTimeout(function(){renderSteps(s.steps||[])},100);
  });
}
function renderSteps(steps){
  var el=document.getElementById('steps-container');if(!el)return;
  dashboardSteps=steps.map(function(s,i){
    return {position:i+1,media_id:s.media_id||'$',preview_id:s.preview_id||'',price:s.price||0,tease_script:s.tease_script||'',offer_script:s.offer_script||'',id:s.id||null};
  });
  if(!dashboardSteps.length){el.innerHTML='<div class="empty"><div class="ico">&#128196;</div><p>Add your first PPV step</p></div>';return}
  var h='';
  dashboardSteps.forEach(function(step,i){
    h+='<div class="panel" style="padding:14px;margin-bottom:8px;border-left:3px solid var(--accent)">';
    h+='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px"><span style="font-size:11px;font-weight:500;color:var(--accent)">PPV '+(i+1)+'</span><button class="btn-ghost" data-action="remove-step" data-step-index="'+i+'" style="padding:2px 8px;font-size:10px">&#128465; Remove</button></div>';
    h+='<div class="g3" style="margin-bottom:8px">';
    h+='<div><label>Media ID</label><div class="row" style="margin-bottom:0"><input id="smedia_'+i+'" value="'+attr(step.media_id||'$')+'" style="flex:1;margin-bottom:0"/><button class="btn-ghost" data-action="pick-media" data-step-index="'+i+'">Browse</button></div></div>';
    h+='<div><label>Preview ID</label><input id="sprev_'+i+'" value="'+attr(step.preview_id||'')+'\"/></div>';
    h+='<div><label>Price ($)</label><input id="sprice_'+i+'" value="'+step.price.toFixed(2)+'"/></div></div>';
    h+='<div class="g3"><div><label>Tease Script</label><textarea id="stease_'+i+'" rows="2">'+esc(step.tease_script||'')+'</textarea></div>';
    h+='<div><label>Offer Script</label><textarea id="soffer_'+i+'" rows="2">'+esc(step.offer_script||'')+'</textarea></div></div></div>';
  });
  el.innerHTML=h;
}
function addStep(){var s=dashboardSteps;s.push({media_id:'$',preview_id:'',price:0,tease_script:'',offer_script:''});renderSteps(s)}
function removeStep(idx){var s=dashboardSteps;s.splice(idx,1);renderSteps(s)}
function pickMedia(idx){
  var albums=dashboardAlbums;
  if(!albums.length){alert('No vault albums');return}
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
    return {position:i+1,media_id:(document.getElementById('smedia_'+i)||{}).value||'',preview_id:(document.getElementById('sprev_'+i)||{}).value||'',price:parseFloat((document.getElementById('sprice_'+i)||{}).value)||0,tease_script:(document.getElementById('stease_'+i)||{}).value||'',offer_script:(document.getElementById('soffer_'+i)||{}).value||''};
  });
  var body={name:name,trigger:trigger,funnel_stage:funnel,is_active:active,steps:stepData};
  var url='/api/sequences'+(editSeqId?'/'+editSeqId:'');
  M(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(function(r){
    if(!r.ok){alert('Save failed');return}
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
            "img-src 'self' data:; "
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
        return bool(hostname and hostname.lower() in self.server.allowed_hosts)

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
        if not self._authorize():
            return
        if p in ("/","/dashboard"): return self.h(DASHBOARD_HTML)
        if p=="/api/conversations": return self._conv()
        if p.startswith("/api/conversations/"): return self._conv_detail(p.rsplit("/",1)[-1])
        if p=="/api/fans": return self._fans()
        if p=="/api/vault": return self.j({"files":_list_vault(self.vault_dir),"dir":self.vault_dir})
        if p=="/api/kpis": return self._kpi()
        if p=="/api/scripts": return self._scrs()
        if p=="/api/connection": return self._conn(False)
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
        if not self._authorize(require_csrf=True):
            return
        p = self.path.split("?")[0]
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
        if p=="/api/sequences": return self._seq_create(b)
        if p.startswith("/api/sequences/") and len(p.split("/"))==4: return self._seq_update(p.rsplit("/",1)[-1], b)
        if p=="/api/bot/toggle": return self._bot_toggle(b)
        self.j({"error":"not found"},404)

    def do_DELETE(self):
        if not self._authorize(require_csrf=True):
            return
        p = self.path.split("?")[0]
        if p.startswith("/api/sequences/") and len(p.split("/"))==4: return self._seq_delete(p.rsplit("/",1)[-1])
        self.j({"error":"not found"},404)

    def do_OPTIONS(self):
        self.j({"error": "method not allowed"}, 405)

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
        if not CREATOR_ID_PATTERN.fullmatch(cid):
            return self.j({"error": "invalid creator id"}, 400)
        p = Path(PERSONA_DIR)/f"{cid}.yaml"
        return self.j({"creator_id":cid,"yaml":p.read_text(encoding="utf-8") if p.exists() else ""})

    def _pers_post(self,q,b):
        cid = (q.get("creator",[None])or[None])[0] or (self.bot.creator_id if self.bot else "sunny_charm")
        if not CREATOR_ID_PATTERN.fullmatch(cid):
            return self.j({"error": "invalid creator id"}, 400)
        try: yaml.safe_load(b)
        except yaml.YAMLError as e: return self.j({"error":str(e)},400)
        p = Path(PERSONA_DIR); p.mkdir(parents=True,exist_ok=True); (p/f"{cid}.yaml").write_text(b, encoding="utf-8")
        return self.j({"status":"ok"})

    def _bible_get(self):
        p = Path(BRAND_BIBLE_PATH)
        return self.j({"content":p.read_text(encoding="utf-8") if p.exists() else "","path":str(p)})

    def _bible_post(self,b):
        p = Path(BRAND_BIBLE_PATH); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(b, encoding="utf-8")
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
                engine=self.bot.note_repo.engine,
                creator_id=self.bot.creator_id,
            )
            store.create_table()
            store.set("bot_enabled", str(new_state).lower())
            return self.j({"enabled": new_state})
        except Exception as e:
            return self.j({"error": str(e)}, 500)

    def log_message(self,*a): pass

class DashboardServer:
    def __init__(
        self,
        bot,
        port=8080,
        vault_dir="/data/videos",
        dashboard_user: Optional[str] = None,
        dashboard_password: Optional[str] = None,
        allowed_hosts: Optional[set[str]] = None,
        csrf_token: Optional[str] = None,
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
        self.csrf_token = self.server.csrf_token
    def handle_request(self): self.server.handle_request()
    def shutdown(self): self.server.shutdown()
