"""Sri Mahabaleswara Temple - website, committee, guidelines, admin and donations (Flask + SQLite).

Run:  pip install -r requirements.txt
      ADMIN_PASSWORD='choose-a-strong-one' SECRET_KEY='long-random-text' python app.py
Open: http://localhost:5070/      Admin: http://localhost:5070/admin  (user: admin)

Optional online payments (Razorpay): set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.
UPI QR / bank-transfer donations work without them: set the UPI ID in Admin > Settings.
Single file on purpose: no templates/static folders to misplace. Uploaded photos go to ./uploads
"""
import base64, csv, hashlib, hmac, io, json, os, secrets, sqlite3, time, urllib.request
from datetime import datetime
from functools import wraps
from urllib.parse import quote

from flask import (Flask, Response, abort, flash, g, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from jinja2 import DictLoader
from markupsafe import Markup
from werkzeug.security import check_password_hash, generate_password_hash

try:
    import segno  # QR codes for UPI
except ImportError:
    segno = None

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.getenv("TEMPLE_DB", os.path.join(BASE, "temple.db"))
UPLOAD_DIR = os.path.join(BASE, "uploads")
RZP_KEY, RZP_SECRET = os.getenv("RAZORPAY_KEY_ID", ""), os.getenv("RAZORPAY_KEY_SECRET", "")
PURPOSES = ["General donation", "Annadana (food offering)", "Abhisheka", "Special pooja", "Temple renovation", "Deepotsava"]
DEFAULTS = {"temple_name": "Sri Mahabaleswara Temple", "tagline": "Om Namah Shivaya",
            "about": "Welcome to Sri Mahabaleswara Temple. Devotees gather here to worship Lord Shiva, seek blessings and serve the community. "
                     "This website shares information about our temple committee, guidelines for devotees and a safe way to offer your donation.",
            "address": "", "phone": "", "email": "", "timings": "", "upi_id": "", "payee_name": "Sri Mahabaleswara Temple", "bank_details": ""}
SAMPLE_GUIDELINES = [
    ("Devotion and cleanliness", "Please keep the temple premises clean and maintain silence and respect inside the sanctum area."),
    ("Dress and conduct", "Devotees are requested to dress modestly and follow the instructions of the temple staff and volunteers."),
    ("Offerings and donations", "All donations are voluntary and are recorded. A receipt is issued for every confirmed donation."),
    ("Committee transparency", "The committee maintains accounts of income and expenses and shares them with devotees on request."),
    ("Serving devotees", "Elders, children and differently-abled devotees are given priority and help during darshan and festivals.")]

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)  # set SECRET_KEY so logins survive restarts
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", MAX_CONTENT_LENGTH=4 * 1024 * 1024)

LINGA_SVG = """<svg viewBox="0 0 300 340" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Shiva Linga">
<defs><radialGradient id="gl" cx="50%" cy="45%" r="55%"><stop offset="0" stop-color="#fff3b0"/><stop offset=".5" stop-color="#ffb347" stop-opacity=".75"/><stop offset="1" stop-color="#ff7a00" stop-opacity="0"/></radialGradient>
<linearGradient id="lg" x1="0" x2="1"><stop offset="0" stop-color="#14141c"/><stop offset=".45" stop-color="#53536b"/><stop offset="1" stop-color="#0b0b11"/></linearGradient>
<linearGradient id="pg" x1="0" x2="1"><stop offset="0" stop-color="#8d6e63"/><stop offset=".5" stop-color="#e2c3a3"/><stop offset="1" stop-color="#6d4c41"/></linearGradient></defs>
<circle cx="150" cy="150" r="148" fill="url(#gl)"/>
<path d="M44 280 Q150 248 256 280 L240 304 Q150 328 60 304Z" fill="url(#pg)"/><ellipse cx="150" cy="270" rx="82" ry="14" fill="#c9a07c"/>
<path d="M104 270 L110 112 Q150 82 190 112 L196 270 Q150 288 104 270Z" fill="url(#lg)"/>
<g stroke="#fff" stroke-width="5" stroke-linecap="round" opacity=".93"><path d="M114 176 Q150 188 186 176"/><path d="M113 197 Q150 209 187 197"/><path d="M112 218 Q150 230 188 218"/></g>
<circle cx="150" cy="150" r="7" fill="#ff3d00"/>
<g transform="translate(150 100)"><ellipse rx="9" ry="22" fill="#2e7d32" transform="rotate(-38) translate(0 -14)"/><ellipse rx="9" ry="22" fill="#43a047" transform="translate(0 -20)"/><ellipse rx="9" ry="22" fill="#2e7d32" transform="rotate(38) translate(0 -14)"/></g>
<g fill="#ffb300"><circle cx="112" cy="258" r="8"/><circle cx="132" cy="266" r="8" fill="#ff7a00"/><circle cx="154" cy="268" r="8"/><circle cx="176" cy="266" r="8" fill="#ff7a00"/><circle cx="196" cy="258" r="8"/></g>
<g class="flame"><path d="M38 262 Q26 284 38 292 Q50 284 38 262Z" fill="#ffd54f"/><path d="M262 262 Q250 284 262 292 Q274 284 262 262Z" fill="#ffd54f"/></g>
<path d="M22 294 Q38 320 54 294Z" fill="#c2185b"/><path d="M246 294 Q262 320 278 294Z" fill="#c2185b"/></svg>"""

CSS = """:root{--saf:#ff7a00;--mar:#7a1020;--gold:#f5b700;--teal:#00897b;--pink:#d81b60;--ind:#3949ab;--cream:#fff7e6;--ink:#2b1a14}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--cream);color:var(--ink);font:16px/1.6 Poppins,"Noto Sans Kannada",system-ui,sans-serif}
a{color:inherit;text-decoration:none}img{max-width:100%}.w{max-width:1100px;margin:0 auto;padding:0 18px}
.toran{height:9px;background:repeating-linear-gradient(90deg,#ff7a00 0 14px,#f5b700 14px 28px,#d81b60 28px 42px,#00897b 42px 56px)}
header.top{background:linear-gradient(90deg,var(--mar),#b0123f 55%,var(--saf));color:#fff;position:sticky;top:0;z-index:20;box-shadow:0 4px 18px rgba(122,16,32,.35)}
.nav{display:flex;justify-content:space-between;align-items:center;min-height:62px;gap:10px;flex-wrap:wrap}.brand{font-weight:700;font-size:18px;display:flex;gap:10px;align-items:center}.om{font-size:28px;color:var(--gold)}
.nav nav a{margin-left:16px;font-size:14px;opacity:.95}.nav nav a:hover{color:var(--gold)}
.btn,button{background:linear-gradient(135deg,var(--saf),var(--pink));color:#fff;border:0;border-radius:999px;padding:11px 24px;font:600 14px inherit;cursor:pointer;display:inline-block;box-shadow:0 6px 16px rgba(216,27,96,.3);transition:transform .15s}
.btn:hover,button:hover{transform:translateY(-2px)}.btn.gold{background:linear-gradient(135deg,#ffd54f,var(--saf));color:var(--mar)}.btn.ghost{background:transparent;border:2px solid #fff;box-shadow:none}.sm{padding:6px 14px;font-size:12px}.btn.red{background:linear-gradient(135deg,#e53935,#b71c1c)}.btn.green{background:linear-gradient(135deg,#43a047,#00897b)}
.hero{background:linear-gradient(135deg,#5b0a1c,#b0123f 45%,#ff7a00);color:#fff;padding:54px 0;position:relative;overflow:hidden}
.hero:before{content:"";position:absolute;inset:0;background:radial-gradient(circle at 80% 30%,rgba(255,213,79,.35),transparent 45%),radial-gradient(circle at 10% 90%,rgba(0,137,123,.35),transparent 40%)}
.hero .g{display:grid;grid-template-columns:1.1fr .9fr;gap:30px;align-items:center;position:relative}
.kn{font-size:clamp(28px,5vw,48px);line-height:1.2;margin:.1em 0;background:linear-gradient(90deg,#fff,#ffd54f,#ff9e80,#fff);background-size:200%;-webkit-background-clip:text;background-clip:text;color:transparent;animation:shine 6s linear infinite}
@keyframes shine{to{background-position:200% 0}}.hero h2{font-weight:400;margin:0 0 14px;font-size:20px;color:#ffe9b0}.hero p{max-width:520px;color:#fff1d6}
.deity{text-align:center}.deity svg,.deity .photo{width:min(320px,80%);filter:drop-shadow(0 0 30px rgba(255,213,79,.7));animation:float 5s ease-in-out infinite}
.deity .photo{border-radius:50%;aspect-ratio:1;object-fit:cover;border:6px solid var(--gold)}.deity small{display:block;margin-top:8px;color:#ffe9b0;letter-spacing:.08em}
@keyframes float{50%{transform:translateY(-10px)}}.flame{transform-origin:50% 100%;animation:flick .5s ease-in-out infinite alternate}@keyframes flick{to{transform:scale(1.15,.92);opacity:.85}}
section{padding:54px 0}h2.t{font-size:clamp(24px,3.4vw,34px);margin:0 0 6px;text-align:center}.sub{text-align:center;margin:0 auto 28px;max-width:640px;opacity:.85}
.about{background:#fff}.chips{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin-top:20px}
.chip{border-radius:16px;padding:16px;color:#fff;font-weight:600}.chip small{display:block;font-weight:400;opacity:.9}.chip:nth-child(1){background:linear-gradient(135deg,#ff7a00,#ffb300)}.chip:nth-child(2){background:linear-gradient(135deg,#00897b,#26c6da)}.chip:nth-child(3){background:linear-gradient(135deg,#d81b60,#ff7043)}.chip:nth-child(4){background:linear-gradient(135deg,#3949ab,#7e57c2)}
.c0{--k:#ff7a00}.c1{--k:#d81b60}.c2{--k:#00897b}.c3{--k:#3949ab}.c4{--k:#f5b700}.c5{--k:#7a1020}
.comm{background:linear-gradient(180deg,#ffe9c7,#ffd9e4)}.mgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:22px}
.mem{text-align:center;background:#fff;border-radius:20px;padding:22px 12px;box-shadow:0 8px 24px rgba(122,16,32,.12);border-bottom:6px solid var(--k);transition:transform .2s}.mem:hover{transform:translateY(-6px)}
.ring{width:128px;height:128px;margin:0 auto 12px;border-radius:50%;padding:5px;background:conic-gradient(var(--k),var(--gold),#fff,var(--k));display:grid;place-items:center}
.ring img{width:100%;height:100%;border-radius:50%;object-fit:cover;border:3px solid #fff}.ring span{width:100%;height:100%;border-radius:50%;background:var(--k);color:#fff;display:grid;place-items:center;font-size:44px;font-weight:700;border:3px solid #fff}
.mem h3{margin:4px 0;font-size:17px}.mem em{display:inline-block;background:var(--k);color:#fff;border-radius:999px;padding:2px 12px;font-size:12px;font-style:normal}
.guide{background:linear-gradient(135deg,#00695c,#3949ab);color:#fff}.ggrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}
.gd{background:#fff;color:var(--ink);border-radius:16px;padding:18px;border-top:7px solid var(--k);position:relative}.gd b.n{position:absolute;right:14px;top:-18px;background:var(--k);color:#fff;width:36px;height:36px;border-radius:50%;display:grid;place-items:center;border:3px solid #fff}.gd h3{margin:0 0 6px;color:var(--k)}.gd p{margin:0;font-size:14px}
.give{background:linear-gradient(135deg,#ffd54f,#ff7a00 55%,#d81b60);color:#fff;text-align:center}.give h2{margin:0 0 8px;font-size:clamp(24px,4vw,38px)}.amts{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin:18px 0}.amts a{background:#fff;color:var(--mar);padding:8px 20px;border-radius:999px;font-weight:700}
.contact{background:var(--mar);color:#fff}.cgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}.cgrid div{background:rgba(255,255,255,.1);border-radius:14px;padding:14px}.cgrid small{opacity:.7;display:block}
footer{background:#3b0612;color:#ffd9b0;text-align:center;padding:18px;font-size:13px}
.card{background:#fff;border-radius:20px;padding:24px;box-shadow:0 10px 30px rgba(122,16,32,.15);border-top:8px solid var(--saf)}
label{font-size:13px;font-weight:600;color:#6d4c41;display:block;margin:12px 0 4px}input,select,textarea{width:100%;padding:10px 12px;border:2px solid #f1d9bf;border-radius:12px;font:inherit;background:#fffdf8}input:focus,select:focus,textarea:focus{outline:0;border-color:var(--pink)}
.fl{padding:12px 16px;border-radius:12px;margin:14px 0;background:#e0f7f1;border-left:6px solid var(--teal)}.fl.e{background:#ffe5e5;border-color:#d32f2f}
.amount{font-size:44px;font-weight:700;background:linear-gradient(90deg,var(--saf),var(--pink));-webkit-background-clip:text;background-clip:text;color:transparent}.qr{max-width:240px;margin:10px auto;background:#fff;padding:8px;border-radius:14px;border:3px solid var(--gold)}.qr svg{width:100%;height:auto}
.badge{padding:3px 12px;border-radius:999px;color:#fff;font-size:12px;font-weight:700}.pending{background:#78909c}.claimed{background:#fb8c00}.confirmed{background:#2e9d4f}.rejected{background:#d32f2f}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:14px}table{width:100%;border-collapse:collapse}th,td{padding:9px 10px;text-align:left;border-bottom:1px solid #f1e3d0;font-size:14px}th{background:#fff1dc;color:#7a1020;font-size:12px}.tw{overflow-x:auto}
.adm{display:grid;grid-template-columns:230px 1fr;min-height:100vh}.side{background:linear-gradient(180deg,#311b92,#7a1020 60%,#e65100);color:#fff;padding:20px 14px}.side h3{margin:0 0 16px}.side a{display:block;padding:10px 14px;border-radius:12px;margin-bottom:6px;font-size:14px}.side a:hover,.side a.on{background:rgba(255,255,255,.2)}
.main{padding:22px;background:linear-gradient(135deg,#fff7e6,#f3e8ff)}.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-bottom:20px}
.stat{border-radius:18px;padding:18px;color:#fff;box-shadow:0 8px 20px rgba(0,0,0,.15)}.stat b{display:block;font-size:30px}.stat:nth-child(1){background:linear-gradient(135deg,#2e7d32,#00bfa5)}.stat:nth-child(2){background:linear-gradient(135deg,#fb8c00,#ff5252)}.stat:nth-child(3){background:linear-gradient(135deg,#3949ab,#8e24aa)}.stat:nth-child(4){background:linear-gradient(135deg,#d81b60,#ff7043)}
.thumb{width:44px;height:44px;border-radius:50%;object-fit:cover;vertical-align:middle;margin-right:8px;border:2px solid var(--gold)}
@media(max-width:800px){.hero .g,.g2{grid-template-columns:1fr}.adm{grid-template-columns:1fr}.side{display:flex;flex-wrap:wrap;gap:6px;align-items:center}.side h3{width:100%;margin:0}.side a{margin:0}}"""

HEAD = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+Kannada:wght@400;700&family=Poppins:wght@400;600;700&display=swap">
<title>{% block title %}{{ S.temple_name }}{% endblock %}</title><style>""" + CSS + """</style></head><body>"""
FLASHES = """<div class="w">{% for cat, m in get_flashed_messages(with_categories=true) %}<div class="fl {{ 'e' if cat=='error' }}">{{ m }}</div>{% endfor %}</div>"""

T = {
"base.html": HEAD + """<div class="toran"></div><header class="top"><div class="w nav"><a class="brand" href="{{ url_for('index') }}"><span class="om">ॐ</span>{{ S.temple_name }}</a>
<nav><a href="{{ url_for('index') }}#about">About</a><a href="{{ url_for('index') }}#committee">Committee</a><a href="{{ url_for('index') }}#guidelines">Guidelines</a><a href="{{ url_for('index') }}#contact">Contact</a><a class="btn gold sm" href="{{ url_for('donate') }}">🙏 Donate</a></nav></div></header>""" + FLASHES + """{% block body %}{% endblock %}
<footer>© {{ year }} {{ S.temple_name }} · <a href="{{ url_for('login') }}">Admin</a></footer></body></html>""",

"index.html": """{% extends "base.html" %}{% block body %}
<div class="hero"><div class="w g"><div><div class="kn">ಶ್ರೀ ಮಹಾಬಲೇಶ್ವರ ದೇವಸ್ಥಾನ</div><h2>{{ S.tagline }} · ಓಂ ನಮಃ ಶಿವಾಯ</h2><p>{{ S.about }}</p>
<a class="btn gold" href="{{ url_for('donate') }}">🙏 Offer a donation</a> <a class="btn ghost" href="#committee">Meet the committee</a></div>
<div class="deity">{% if deity.image %}<img class="photo" src="{{ url_for('uploads', name=deity.image) }}" alt="{{ deity.caption }}">{% else %}{{ linga }}{% endif %}<small>{{ deity.caption }}</small></div></div></div>
<section id="about" class="about"><div class="w"><h2 class="t">Darshan &amp; temple information</h2><p class="sub">Plan your visit to the temple.</p><div class="chips">
<div class="chip">🕒 Timings<small>{{ S.timings or 'To be updated' }}</small></div><div class="chip">📍 Address<small>{{ S.address or 'To be updated' }}</small></div><div class="chip">📞 Phone<small>{{ S.phone or 'To be updated' }}</small></div><div class="chip">✉️ Email<small>{{ S.email or 'To be updated' }}</small></div></div></div></section>
<section id="committee" class="comm"><div class="w"><h2 class="t">Temple committee</h2><p class="sub">The devotees who serve and guide the temple.</p>
<div class="mgrid">{% for m in members %}<div class="mem c{{ loop.index0 % 6 }}"><div class="ring">{% if m.photo %}<img src="{{ url_for('uploads', name=m.photo) }}" alt="{{ m.name }}" loading="lazy">{% else %}<span>{{ m.name[:1] }}</span>{% endif %}</div><h3>{{ m.name }}</h3><em>{{ m.role }}</em></div>
{% else %}<p class="sub">Committee members will be listed here soon.</p>{% endfor %}</div></div></section>
<section id="guidelines" class="guide"><div class="w"><h2 class="t">Committee guidelines</h2><p class="sub">Principles that guide our temple and our devotees.</p>
<div class="ggrid">{% for gd in guides %}<div class="gd c{{ loop.index0 % 6 }}"><b class="n">{{ loop.index }}</b><h3>{{ gd.title }}</h3><p>{{ gd.body }}</p></div>{% else %}<p class="sub">Guidelines will be published soon.</p>{% endfor %}</div></div></section>
<section class="give"><div class="w"><h2>🙏 Support the temple</h2><p>Your offering helps pooja, annadana and temple upkeep. Pay safely by UPI{% if rzp %}, card or net banking{% endif %}.</p>
<div class="amts">{% for a in [101,251,501,1001,2501] %}<a href="{{ url_for('donate') }}?amount={{ a }}">₹{{ a }}</a>{% endfor %}</div><a class="btn" style="background:#fff;color:var(--mar)" href="{{ url_for('donate') }}">Donate now</a></div></section>
<section id="contact" class="contact"><div class="w"><h2 class="t">Contact</h2><div class="cgrid"><div><small>Address</small>{{ S.address or 'To be updated' }}</div><div><small>Phone</small>{{ S.phone or 'To be updated' }}</div><div><small>Email</small>{{ S.email or 'To be updated' }}</div></div></div></section>{% endblock %}""",

"donate.html": """{% extends "base.html" %}{% block body %}<section><div class="w" style="max-width:560px"><div class="card"><h2 class="t" style="text-align:left">🙏 Make a donation</h2><p>Donations are voluntary. A receipt is issued once the temple office confirms your payment.</p>
<form method="post" action="{{ url_for('donate_create') }}"><input type="hidden" name="_csrf" value="{{ csrf() }}"><div style="position:absolute;left:-9999px"><input name="website" tabindex="-1" autocomplete="off"></div>
<label>Amount (₹) *</label><input name="amount" id="amt" type="number" min="10" max="500000" step="1" required value="{{ amount }}"><div class="amts" style="justify-content:flex-start;margin:8px 0">{% for a in [101,251,501,1001,2501] %}<a href="#" onclick="amt.value={{ a }};return false" style="background:#fff1dc">₹{{ a }}</a>{% endfor %}</div>
<label>Purpose</label><select name="purpose">{% for p in purposes %}<option>{{ p }}</option>{% endfor %}</select>
<div class="g2"><div><label>Your name *</label><input name="name" required maxlength="80"></div><div><label>Phone *</label><input name="phone" required maxlength="15" pattern="[0-9+ ]{10,15}" title="10–15 digits"></div></div>
<label>Email (for receipt)</label><input name="email" type="email" maxlength="100"><label>Message / sankalpa (optional)</label><textarea name="message" rows="2" maxlength="300"></textarea>
<p><button>Continue to payment →</button></p></form></div></div></section>{% endblock %}""",

"pay.html": """{% extends "base.html" %}{% block body %}<section><div class="w" style="max-width:640px"><div class="card" style="text-align:center">
<span class="badge {{ d.status }}">{{ {'pending':'Awaiting payment','claimed':'Payment submitted – awaiting temple confirmation','confirmed':'Confirmed','rejected':'Rejected'}[d.status] }}</span>
<div class="amount">₹{{ '{:,.0f}'.format(d.amount) }}</div><p>{{ d.purpose }} · Ref <b>{{ d.ref }}</b></p>
{% if d.status == 'confirmed' %}<p>🙏 Thank you, {{ d.name }}. May Lord Mahabaleswara bless you and your family.</p><a class="btn green" href="{{ url_for('receipt', ref=d.ref) }}">View / print receipt</a>
{% elif d.status == 'rejected' %}<p>This payment could not be verified. Please contact the temple office with your reference.</p>
{% else %}
{% if rzp %}<h3>Pay online</h3><p class="fl" style="text-align:left">Cards, UPI and net banking via Razorpay.</p><button onclick="payOnline()">Pay ₹{{ '{:,.0f}'.format(d.amount) }} online</button><script src="https://checkout.razorpay.com/v1/checkout.js"></script><hr style="border:0;border-top:2px dashed #f1d9bf;margin:22px 0">{% endif %}
{% if upi %}<h3>Pay with any UPI app</h3>{% if qr %}<div class="qr">{{ qr }}</div>{% endif %}<p><a class="btn" href="{{ upi }}">Open UPI app</a></p><p class="sub" style="font-size:13px">UPI ID: <b>{{ S.upi_id }}</b> ({{ S.payee_name }})</p>{% endif %}
{% if S.bank_details %}<h3>Bank transfer</h3><pre style="text-align:left;background:#fffdf8;border:2px solid #f1d9bf;border-radius:12px;padding:12px;white-space:pre-wrap">{{ S.bank_details }}</pre>{% endif %}
{% if not upi and not S.bank_details and not rzp %}<p class="fl e">Online payment is not set up yet. Please contact the temple office with reference {{ d.ref }}.</p>{% endif %}
{% if upi or S.bank_details %}<form method="post" action="{{ url_for('donate_utr', ref=d.ref) }}" style="text-align:left;margin-top:18px"><input type="hidden" name="_csrf" value="{{ csrf() }}"><label>After paying, enter your UPI / bank transaction ID</label><input name="txn" required minlength="6" maxlength="40" pattern="[A-Za-z0-9]+" placeholder="e.g. 412345678901"><p><button>I have paid</button></p></form>{% endif %}
{% endif %}</div></div></section>
{% if rzp and d.status in ('pending','claimed') %}<script>async function payOnline(){const r=await fetch("{{ url_for('rzp_order', ref=d.ref) }}",{method:"POST",headers:{"X-CSRF":"{{ csrf() }}"}});const o=await r.json();if(!r.ok){alert(o.error||"Could not start payment");return}
new Razorpay({key:o.key,amount:o.amount,currency:"INR",name:o.name,description:o.desc,order_id:o.order_id,prefill:{name:o.donor,contact:o.phone},handler:async function(res){const f=new FormData();f.append("razorpay_payment_id",res.razorpay_payment_id);f.append("razorpay_order_id",res.razorpay_order_id);f.append("razorpay_signature",res.razorpay_signature);f.append("_csrf","{{ csrf() }}");await fetch("{{ url_for('rzp_verify', ref=d.ref) }}",{method:"POST",body:f});location.reload()}}).open()}</script>{% endif %}{% endblock %}""",

"receipt.html": """<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Receipt {{ d.ref }}</title><style>""" + CSS + """body{background:#fff}.r{max-width:560px;margin:24px auto;border:4px double #7a1020;padding:26px;border-radius:12px}</style></head><body><div class="r"><div class="toran"></div><h2 style="text-align:center;color:#7a1020">ॐ {{ S.temple_name }}</h2><p style="text-align:center">{{ S.address }}</p><h3 style="text-align:center">Donation receipt</h3>
<table><tr><th>Receipt / Ref</th><td>{{ d.ref }}</td></tr><tr><th>Date</th><td>{{ d.confirmed_at or d.created }}</td></tr><tr><th>Donor</th><td>{{ d.name }}</td></tr><tr><th>Purpose</th><td>{{ d.purpose }}</td></tr><tr><th>Amount</th><td><b>₹{{ '{:,.2f}'.format(d.amount) }}</b></td></tr><tr><th>Payment</th><td>{{ d.method }} · {{ d.txn }}</td></tr></table>
<p style="text-align:center;margin-top:18px">🙏 Thank you for your offering.</p><p style="text-align:center"><button onclick="print()" class="btn sm">Print</button></p></div></body></html>""",

"login.html": """{% extends "base.html" %}{% block body %}<section><div class="w" style="max-width:380px"><div class="card"><h2 class="t">Admin login</h2><form method="post"><input type="hidden" name="_csrf" value="{{ csrf() }}"><label>Username</label><input name="username" autofocus required><label>Password</label><input name="password" type="password" required><p><button>Log in</button></p></form></div></div></section>{% endblock %}""",

"abase.html": HEAD + """<div class="adm"><aside class="side"><h3>ॐ Temple Admin</h3>
{% set nav = [('dashboard','📊 Dashboard'),('donations','💰 Donations'),('members','👥 Committee'),('guidelines','📜 Guidelines'),('deity','🕉 Deity image'),('settings','⚙ Settings')] %}
{% for ep, label in nav %}<a class="{{ 'on' if request.endpoint==ep }}" href="{{ url_for(ep) }}">{{ label }}</a>{% endfor %}<a href="{{ url_for('index') }}" target="_blank">🌐 View website</a>
<form method="post" action="{{ url_for('logout') }}"><input type="hidden" name="_csrf" value="{{ csrf() }}"><button class="sm" style="margin-top:8px">Log out</button></form></aside>
<main class="main">""" + FLASHES.replace('class="w"', '') + """{% block body %}{% endblock %}</main></div></body></html>""",

"dashboard.html": """{% extends "abase.html" %}{% block body %}<h2>Dashboard</h2>{% if weak %}<div class="fl e">You are still using the default password. Change it in Settings.</div>{% endif %}
<div class="stats"><div class="stat"><b>₹{{ '{:,.0f}'.format(total) }}</b>Confirmed donations</div><div class="stat"><b>{{ claimed }}</b>Awaiting verification</div><div class="stat"><b>{{ ndon }}</b>Confirmed gifts</div><div class="stat"><b>{{ nmem }}</b>Committee members</div></div>
<div class="card"><h3>Recent donations</h3><div class="tw"><table><tr><th>Date</th><th>Donor</th><th>Purpose</th><th>Amount</th><th>Status</th></tr>{% for r in rows %}<tr><td>{{ r.created }}</td><td>{{ r.name }}</td><td>{{ r.purpose }}</td><td>₹{{ '{:,.0f}'.format(r.amount) }}</td><td><span class="badge {{ r.status }}">{{ r.status }}</span></td></tr>{% else %}<tr><td colspan="5">No donations yet.</td></tr>{% endfor %}</table></div></div>{% endblock %}""",

"donations.html": """{% extends "abase.html" %}{% block body %}<h2>Donations</h2><p>Filter: {% for s in ['all','claimed','pending','confirmed','rejected'] %}<a class="badge {{ s if s!='all' else 'pending' }}" href="?status={{ s }}">{{ s }}</a> {% endfor %} <a class="btn sm green" href="{{ url_for('donations_csv') }}">⬇ Export CSV</a></p>
<div class="card"><div class="tw"><table><tr><th>Date</th><th>Ref</th><th>Donor</th><th>Phone</th><th>Purpose</th><th>Amount</th><th>Method / Txn</th><th>Status</th><th></th></tr>
{% for r in rows %}<tr><td>{{ r.created }}</td><td>{{ r.ref }}</td><td>{{ r.name }}</td><td>{{ r.phone }}</td><td>{{ r.purpose }}</td><td>₹{{ '{:,.0f}'.format(r.amount) }}</td><td>{{ r.method }} {{ r.txn }}</td><td><span class="badge {{ r.status }}">{{ r.status }}</span></td>
<td>{% if r.status in ('pending','claimed') %}<form method="post" action="{{ url_for('donation_set', did=r.id) }}" style="display:flex;gap:4px"><input type="hidden" name="_csrf" value="{{ csrf() }}"><button class="sm green" name="to" value="confirmed">Confirm</button><button class="sm red" name="to" value="rejected">Reject</button></form>{% elif r.status=='confirmed' %}<a class="btn sm" href="{{ url_for('receipt', ref=r.ref) }}" target="_blank">Receipt</a>{% endif %}</td></tr>{% else %}<tr><td colspan="9">No donations.</td></tr>{% endfor %}</table></div></div>
<p class="sub" style="text-align:left">Confirm a UPI/bank donation only after you see the amount in the temple's account statement.</p>{% endblock %}""",

"members.html": """{% extends "abase.html" %}{% block body %}<h2>Committee members</h2><div class="card" style="margin-bottom:18px"><form method="post" enctype="multipart/form-data"><input type="hidden" name="_csrf" value="{{ csrf() }}"><div class="g2">
<div><label>Name *</label><input name="name" required maxlength="80"></div><div><label>Role / position *</label><input name="role" required maxlength="60" placeholder="e.g. President"></div>
<div><label>Photo (JPG, PNG or WEBP, max 4 MB)</label><input type="file" name="photo" accept="image/png,image/jpeg,image/webp"></div><div><label>Display order (1 = first)</label><input name="sort" type="number" value="{{ nxt }}" min="1"></div></div><p><button>Add member</button></p></form></div>
<div class="card"><div class="tw"><table><tr><th>#</th><th>Member</th><th>Role</th><th></th></tr>{% for m in rows %}<tr><td>{{ m.sort }}</td><td>{% if m.photo %}<img class="thumb" src="{{ url_for('uploads', name=m.photo) }}" alt="">{% endif %}{{ m.name }}</td><td>{{ m.role }}</td>
<td><div style="display:flex;gap:6px"><a class="btn sm green" href="{{ url_for('member_edit', mid=m.id) }}">Edit</a><form method="post" action="{{ url_for('member_delete', mid=m.id) }}" onsubmit="return confirm('Remove this member?')"><input type="hidden" name="_csrf" value="{{ csrf() }}"><button class="sm red">Delete</button></form></div></td></tr>{% else %}<tr><td colspan="4">No members yet.</td></tr>{% endfor %}</table></div></div>{% endblock %}""",

"guidelines.html": """{% extends "abase.html" %}{% block body %}<h2>Committee guidelines</h2><p class="fl">The starter guidelines are generic samples. Edit or delete them so they reflect your committee's real rules.</p>
<div class="card" style="margin-bottom:18px"><form method="post"><input type="hidden" name="_csrf" value="{{ csrf() }}"><label>Title *</label><input name="title" required maxlength="80"><label>Guideline text *</label><textarea name="body" rows="3" required maxlength="600"></textarea><p><button>Add guideline</button></p></form></div>
<div class="card"><table>{% for r in rows %}<tr><td><b>{{ r.title }}</b><br>{{ r.body }}</td><td style="width:90px"><form method="post" action="{{ url_for('guideline_delete', gid=r.id) }}"><input type="hidden" name="_csrf" value="{{ csrf() }}"><button class="sm red">Delete</button></form></td></tr>{% else %}<tr><td>No guidelines yet.</td></tr>{% endfor %}</table></div>{% endblock %}""",

"member_edit.html": """{% extends "abase.html" %}{% block body %}<h2>Edit committee member</h2><div class="card" style="max-width:640px"><form method="post" enctype="multipart/form-data"><input type="hidden" name="_csrf" value="{{ csrf() }}">
<div style="text-align:center">{% if m.photo %}<img src="{{ url_for('uploads', name=m.photo) }}" alt="" style="width:120px;height:120px;border-radius:50%;object-fit:cover;border:4px solid var(--gold)">{% endif %}</div>
<div class="g2"><div><label>Name *</label><input name="name" required maxlength="80" value="{{ m.name }}"></div><div><label>Role / position *</label><input name="role" required maxlength="60" value="{{ m.role }}"></div>
<div><label>Replace photo (JPG, PNG, WEBP, max 4 MB)</label><input type="file" name="photo" accept="image/png,image/jpeg,image/webp"></div><div><label>Display order</label><input name="sort" type="number" min="1" value="{{ m.sort }}"></div></div>
<p><button>Save changes</button> <a class="btn sm" href="{{ url_for('members') }}">Cancel</a></p></form></div>{% endblock %}""",
"deity.html": """{% extends "abase.html" %}{% block body %}<h2>Deity image</h2><div class="card"><div style="text-align:center;max-width:260px;margin:0 auto">{% if deity.image %}<img src="{{ url_for('uploads', name=deity.image) }}" alt="" style="border-radius:50%;aspect-ratio:1;object-fit:cover;border:5px solid var(--gold)">{% else %}{{ linga }}{% endif %}</div>
<form method="post" enctype="multipart/form-data"><input type="hidden" name="_csrf" value="{{ csrf() }}"><label>Upload the temple's own photo of the deity / linga (JPG, PNG, WEBP, max 4 MB)</label><input type="file" name="image" accept="image/png,image/jpeg,image/webp"><label>Caption</label><input name="caption" value="{{ deity.caption }}" maxlength="80"><p><button>Save</button>
{% if deity.image %}<button class="red" name="remove" value="1">Remove photo (use illustration)</button>{% endif %}</p></form><p class="sub" style="text-align:left">Until you upload a photo, the site shows a colourful illustration of the Shiva linga.</p></div>{% endblock %}""",

"settings.html": """{% extends "abase.html" %}{% block body %}<h2>Settings</h2><div class="card" style="max-width:680px"><form method="post"><input type="hidden" name="_csrf" value="{{ csrf() }}">
{% for k,l,t in fields %}<label>{{ l }}</label>{% if t=='area' %}<textarea name="{{ k }}" rows="3" maxlength="600">{{ S.get(k,'') }}</textarea>{% else %}<input name="{{ k }}" value="{{ S.get(k,'') }}" maxlength="200">{% endif %}{% endfor %}
<p class="fl">Online card / net-banking payments (Razorpay) are <b>{{ 'enabled' if rzp else 'not enabled' }}</b>. They are switched on with the RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET environment variables.</p>
<label>New admin password (leave blank to keep; min 10 characters)</label><input name="new_password" type="password" autocomplete="new-password"><p><button>Save settings</button></p></form></div>{% endblock %}""",
}
app.jinja_loader = DictLoader(T)


# ---------------- database ----------------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()


def init_db():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS admin(username TEXT PRIMARY KEY, pw TEXT);
    CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
    CREATE TABLE IF NOT EXISTS members(id INTEGER PRIMARY KEY, name TEXT, role TEXT, photo TEXT, sort INTEGER);
    CREATE TABLE IF NOT EXISTS guidelines(id INTEGER PRIMARY KEY, title TEXT, body TEXT, sort INTEGER);
    CREATE TABLE IF NOT EXISTS donations(id INTEGER PRIMARY KEY, ref TEXT UNIQUE, created TEXT, confirmed_at TEXT, name TEXT, phone TEXT, email TEXT,
      purpose TEXT, amount REAL, message TEXT, method TEXT DEFAULT '', txn TEXT DEFAULT '', status TEXT DEFAULT 'pending', rzp_order TEXT DEFAULT '');""")
    if not c.execute("SELECT 1 FROM admin").fetchone():
        c.execute("INSERT INTO admin VALUES('admin',?)", (generate_password_hash(os.getenv("ADMIN_PASSWORD", "admin123")),))
    if not c.execute("SELECT 1 FROM guidelines").fetchone():
        c.executemany("INSERT INTO guidelines(title,body,sort) VALUES(?,?,?)", [(t, b, i) for i, (t, b) in enumerate(SAMPLE_GUIDELINES, 1)])
    sample = os.path.join(UPLOAD_DIR, "committee_member_1.jpg")  # supplied photo: shown once, then managed from Admin
    if os.path.exists(sample) and not c.execute("SELECT 1 FROM members").fetchone():
        c.execute("INSERT INTO members(name,role,photo,sort) VALUES(?,?,?,1)", ("Committee Member", "Position (edit in Admin)", "committee_member_1.jpg"))
    c.commit()
    c.close()


def settings_all():
    s = dict(DEFAULTS)
    s.update({r["k"]: r["v"] for r in db().execute("SELECT k,v FROM settings")})
    return s


def deity_info():
    s = settings_all()
    return {"image": s.get("deity_image", ""), "caption": s.get("deity_caption") or "Sri Mahabaleswara"}


# ---------------- security helpers ----------------
def csrf():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


@app.context_processor
def inject():
    return dict(S=settings_all(), csrf=csrf, year=datetime.now().year, linga=Markup(LINGA_SVG), rzp=bool(RZP_KEY and RZP_SECRET))


@app.before_request
def check_csrf():
    if request.method == "POST":
        tok = request.form.get("_csrf") or request.headers.get("X-CSRF", "")
        if not secrets.compare_digest(tok, session.get("_csrf", "-")):
            if request.headers.get("X-CSRF") is not None:
                return jsonify(error="Session expired. Reload the page."), 400
            flash("Session expired. Please try again.", "error")
            return redirect(request.referrer or url_for("index"))


@app.after_request
def headers(r):
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["X-Frame-Options"] = "SAMEORIGIN"
    return r


@app.errorhandler(413)
def too_big(_):
    flash("File too large (maximum 4 MB).", "error")
    return redirect(request.referrer or url_for("index"))


def admin_only(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("admin"):
            return redirect(url_for("login"))
        return f(*a, **k)
    return w


def save_image(file):
    """Validate (extension + file signature) and store under a random name. Returns filename or None."""
    if not file or not file.filename:
        return None
    ext = os.path.splitext(file.filename.lower())[1]
    data = file.read(4 * 1024 * 1024 + 1)
    ok = ((ext == ".png" and data[:8] == b"\x89PNG\r\n\x1a\n") or (ext in (".jpg", ".jpeg") and data[:3] == b"\xff\xd8\xff")
          or (ext == ".webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP"))
    if not ok or len(data) > 4 * 1024 * 1024:
        return "invalid"
    name = secrets.token_hex(8) + (".jpg" if ext == ".jpeg" else ext)
    with open(os.path.join(UPLOAD_DIR, name), "wb") as f:
        f.write(data)
    return name


def remove_image(name):
    if name and os.path.basename(name) == name:
        try:
            os.remove(os.path.join(UPLOAD_DIR, name))
        except OSError:
            pass


FAILS = {}  # ip -> (count, first_time)


# ---------------- public ----------------
@app.get("/")
def index():
    c = db()
    return render_template("index.html", members=c.execute("SELECT * FROM members ORDER BY sort,id").fetchall(),
                           guides=c.execute("SELECT * FROM guidelines ORDER BY sort,id").fetchall(), deity=deity_info())


@app.get("/uploads/<path:name>")
def uploads(name):
    return send_from_directory(UPLOAD_DIR, name)


@app.get("/donate")
def donate():
    return render_template("donate.html", purposes=PURPOSES, amount=request.args.get("amount", "501", type=int))


@app.post("/donate")
def donate_create():
    f = request.form
    if f.get("website"):
        return redirect(url_for("index"))
    try:
        amount = int(f.get("amount", ""))
    except ValueError:
        amount = 0
    name, phone, purpose = f.get("name", "").strip()[:80], f.get("phone", "").strip()[:15], f.get("purpose", "")
    digits = "".join(ch for ch in phone if ch.isdigit())
    if not (10 <= amount <= 500000) or not name or len(digits) < 10 or purpose not in PURPOSES:
        flash("Please enter an amount between ₹10 and ₹5,00,000, your name and a valid phone number.", "error")
        return redirect(url_for("donate"))
    ref = "SMT-" + secrets.token_hex(6).upper()
    db().execute("INSERT INTO donations(ref,created,name,phone,email,purpose,amount,message) VALUES(?,?,?,?,?,?,?,?)",
                 (ref, datetime.now().strftime("%Y-%m-%d %H:%M"), name, phone, f.get("email", "")[:100], purpose, amount, f.get("message", "")[:300]))
    db().commit()
    return redirect(url_for("pay", ref=ref))


def get_donation(ref):
    d = db().execute("SELECT * FROM donations WHERE ref=?", (ref,)).fetchone()
    return d or abort(404)


@app.get("/donate/<ref>")
def pay(ref):
    d, s = get_donation(ref), settings_all()
    upi = qr = None
    if s["upi_id"] and d["status"] in ("pending", "claimed"):
        upi = f"upi://pay?pa={quote(s['upi_id'])}&pn={quote(s['payee_name'])}&am={d['amount']:.2f}&cu=INR&tn={quote('Donation ' + d['ref'])}"
        if segno:
            qr = Markup(segno.make(upi, error="m").svg_inline(scale=6, dark="#7a1020", border=2))
    return render_template("pay.html", d=d, upi=upi, qr=qr)


@app.post("/donate/<ref>/utr")
def donate_utr(ref):
    d = get_donation(ref)
    txn = request.form.get("txn", "").strip()
    if d["status"] not in ("pending", "claimed") or not txn.isalnum() or not 6 <= len(txn) <= 40:
        flash("Enter a valid transaction ID (letters and numbers only).", "error")
    else:
        db().execute("UPDATE donations SET method='UPI/Bank',txn=?,status='claimed' WHERE id=?", (txn, d["id"]))
        db().commit()
        flash("Thank you! The temple office will verify your payment and confirm it shortly.")
    return redirect(url_for("pay", ref=ref))


@app.get("/receipt/<ref>")
def receipt(ref):
    d = get_donation(ref)
    if d["status"] != "confirmed":
        abort(404)
    return render_template("receipt.html", d=d)


# ---------------- Razorpay (optional) ----------------
def rzp_sig_ok(order_id, payment_id, sig):
    exp = hmac.new(RZP_SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(exp, sig or "")


@app.post("/donate/<ref>/rzp-order")
def rzp_order(ref):
    d = get_donation(ref)
    if not (RZP_KEY and RZP_SECRET) or d["status"] not in ("pending", "claimed"):
        return jsonify(error="Online payment is not available"), 400
    body = json.dumps({"amount": int(round(d["amount"] * 100)), "currency": "INR", "receipt": d["ref"]}).encode()
    req = urllib.request.Request("https://api.razorpay.com/v1/orders", body, {
        "Content-Type": "application/json", "Authorization": "Basic " + base64.b64encode(f"{RZP_KEY}:{RZP_SECRET}".encode()).decode()})
    try:
        order = json.load(urllib.request.urlopen(req, timeout=15))
    except Exception:
        return jsonify(error="Payment service unreachable. Try again or use UPI."), 502
    db().execute("UPDATE donations SET rzp_order=? WHERE id=?", (order["id"], d["id"]))
    db().commit()
    return jsonify(key=RZP_KEY, order_id=order["id"], amount=order["amount"], name=settings_all()["temple_name"], desc=d["purpose"], donor=d["name"], phone=d["phone"])


@app.post("/donate/<ref>/rzp-verify")
def rzp_verify(ref):
    d, f = get_donation(ref), request.form
    oid, pid = f.get("razorpay_order_id", ""), f.get("razorpay_payment_id", "")
    if RZP_SECRET and oid and oid == d["rzp_order"] and rzp_sig_ok(oid, pid, f.get("razorpay_signature")):
        db().execute("UPDATE donations SET status='confirmed',method='Razorpay',txn=?,confirmed_at=? WHERE id=?",
                     (pid, datetime.now().strftime("%Y-%m-%d %H:%M"), d["id"]))
        db().commit()
        return jsonify(ok=True)
    return jsonify(error="Payment could not be verified"), 400


# ---------------- admin ----------------
@app.route("/admin/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = request.remote_addr
        n, t0 = FAILS.get(ip, (0, time.time()))
        if n >= 5 and time.time() - t0 < 300:
            flash("Too many attempts. Wait 5 minutes.", "error")
            return render_template("login.html")
        row = db().execute("SELECT * FROM admin WHERE username=?", (request.form.get("username", ""),)).fetchone()
        if row and check_password_hash(row["pw"], request.form.get("password", "")):
            FAILS.pop(ip, None)
            session.clear()
            session["admin"] = row["username"]
            return redirect(url_for("dashboard"))
        fresh = time.time() - t0 < 300
        FAILS[ip] = (n + 1 if fresh else 1, t0 if fresh else time.time())
        flash("Wrong username or password.", "error")
    return render_template("login.html")


@app.post("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.get("/admin")
@admin_only
def dashboard():
    c = db()
    one = lambda q: c.execute(q).fetchone()[0]
    pw = c.execute("SELECT pw FROM admin LIMIT 1").fetchone()["pw"]
    return render_template("dashboard.html", total=one("SELECT COALESCE(SUM(amount),0) FROM donations WHERE status='confirmed'"),
                           claimed=one("SELECT COUNT(*) FROM donations WHERE status='claimed'"), ndon=one("SELECT COUNT(*) FROM donations WHERE status='confirmed'"),
                           nmem=one("SELECT COUNT(*) FROM members"), weak=check_password_hash(pw, "admin123"),
                           rows=c.execute("SELECT * FROM donations ORDER BY id DESC LIMIT 8").fetchall())


@app.get("/admin/donations")
@admin_only
def donations():
    st = request.args.get("status", "all")
    q, a = "SELECT * FROM donations", ()
    if st in ("claimed", "pending", "confirmed", "rejected"):
        q, a = q + " WHERE status=?", (st,)
    return render_template("donations.html", rows=db().execute(q + " ORDER BY id DESC LIMIT 1000", a).fetchall())


@app.post("/admin/donations/<int:did>")
@admin_only
def donation_set(did):
    to = request.form.get("to")
    if to in ("confirmed", "rejected"):
        db().execute("UPDATE donations SET status=?, confirmed_at=? WHERE id=? AND status IN ('pending','claimed')",
                     (to, datetime.now().strftime("%Y-%m-%d %H:%M") if to == "confirmed" else None, did))
        db().commit()
        flash(f"Donation marked {to}.")
    return redirect(url_for("donations"))


@app.get("/admin/donations.csv")
@admin_only
def donations_csv():
    safe = lambda v: ("'" + str(v)) if str(v).startswith(("=", "+", "-", "@")) else v  # block spreadsheet formula injection
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Ref", "Date", "Name", "Phone", "Purpose", "Amount", "Method", "Txn", "Status"])
    for r in db().execute("SELECT * FROM donations ORDER BY id"):
        w.writerow([safe(r[k]) for k in ("ref", "created", "name", "phone", "purpose", "amount", "method", "txn", "status")])
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=donations.csv"})


@app.route("/admin/members", methods=["GET", "POST"])
@admin_only
def members():
    c = db()
    if request.method == "POST":
        f = request.form
        name, role = f.get("name", "").strip()[:80], f.get("role", "").strip()[:60]
        photo = save_image(request.files.get("photo"))
        if not name or not role:
            flash("Name and role are required.", "error")
        elif photo == "invalid":
            flash("Photo must be a real JPG, PNG or WEBP image under 4 MB.", "error")
        else:
            c.execute("INSERT INTO members(name,role,photo,sort) VALUES(?,?,?,?)", (name, role, photo, f.get("sort", type=int) or 99))
            c.commit()
            flash("Member added.")
        return redirect(url_for("members"))
    rows = c.execute("SELECT * FROM members ORDER BY sort,id").fetchall()
    return render_template("members.html", rows=rows, nxt=len(rows) + 1)


@app.route("/admin/members/<int:mid>/edit", methods=["GET", "POST"])
@admin_only
def member_edit(mid):
    m = db().execute("SELECT * FROM members WHERE id=?", (mid,)).fetchone() or abort(404)
    if request.method == "POST":
        f = request.form
        name, role = f.get("name", "").strip()[:80], f.get("role", "").strip()[:60]
        photo = save_image(request.files.get("photo"))
        if not name or not role:
            flash("Name and role are required.", "error")
        elif photo == "invalid":
            flash("Photo must be a real JPG, PNG or WEBP image under 4 MB.", "error")
        else:
            if photo:
                remove_image(m["photo"])
            db().execute("UPDATE members SET name=?, role=?, photo=?, sort=? WHERE id=?", (name, role, photo or m["photo"], f.get("sort", type=int) or m["sort"], mid))
            db().commit()
            flash("Member updated.")
            return redirect(url_for("members"))
    return render_template("member_edit.html", m=m)


@app.post("/admin/members/<int:mid>/delete")
@admin_only
def member_delete(mid):
    m = db().execute("SELECT photo FROM members WHERE id=?", (mid,)).fetchone()
    if m:
        remove_image(m["photo"])
        db().execute("DELETE FROM members WHERE id=?", (mid,))
        db().commit()
    return redirect(url_for("members"))


@app.route("/admin/guidelines", methods=["GET", "POST"])
@admin_only
def guidelines():
    if request.method == "POST":
        t, b = request.form.get("title", "").strip()[:80], request.form.get("body", "").strip()[:600]
        if t and b:
            n = db().execute("SELECT COALESCE(MAX(sort),0)+1 FROM guidelines").fetchone()[0]
            db().execute("INSERT INTO guidelines(title,body,sort) VALUES(?,?,?)", (t, b, n))
            db().commit()
            flash("Guideline added.")
        return redirect(url_for("guidelines"))
    return render_template("guidelines.html", rows=db().execute("SELECT * FROM guidelines ORDER BY sort,id").fetchall())


@app.post("/admin/guidelines/<int:gid>/delete")
@admin_only
def guideline_delete(gid):
    db().execute("DELETE FROM guidelines WHERE id=?", (gid,))
    db().commit()
    return redirect(url_for("guidelines"))


def set_setting(k, v):
    db().execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))


@app.route("/admin/deity", methods=["GET", "POST"])
@admin_only
def deity():
    if request.method == "POST":
        old = deity_info()["image"]
        if request.form.get("remove"):
            remove_image(old)
            set_setting("deity_image", "")
            flash("Photo removed. Showing the illustration.")
        else:
            set_setting("deity_caption", request.form.get("caption", "").strip()[:80])
            img = save_image(request.files.get("image"))
            if img == "invalid":
                flash("Image must be a real JPG, PNG or WEBP under 4 MB.", "error")
            elif img:
                remove_image(old)
                set_setting("deity_image", img)
                flash("Deity image updated.")
            else:
                flash("Caption saved.")
        db().commit()
        return redirect(url_for("deity"))
    return render_template("deity.html", deity=deity_info())


FIELDS = [("temple_name", "Temple name", "t"), ("tagline", "Tagline", "t"), ("about", "About the temple", "area"), ("address", "Address", "area"), ("phone", "Phone", "t"),
          ("email", "Email", "t"), ("timings", "Darshan / pooja timings", "area"), ("upi_id", "Temple UPI ID (for donations)", "t"), ("payee_name", "UPI payee name", "t"),
          ("bank_details", "Bank account details (shown to donors who prefer bank transfer)", "area")]


@app.route("/admin/settings", methods=["GET", "POST"])
@admin_only
def settings():
    if request.method == "POST":
        for k, _, _ in FIELDS:
            set_setting(k, request.form.get(k, "").strip()[:600])
        npw = request.form.get("new_password", "")
        if npw:
            if len(npw) < 10:
                flash("Password must be at least 10 characters.", "error")
                return redirect(url_for("settings"))
            db().execute("UPDATE admin SET pw=? WHERE username=?", (generate_password_hash(npw), session["admin"]))
        db().commit()
        flash("Settings saved.")
        return redirect(url_for("settings"))
    return render_template("settings.html", fields=FIELDS)


init_db()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5070"))
    print(f"\nSri Mahabaleswara Temple -> http://localhost:{port}/   admin -> http://localhost:{port}/admin\n")
    app.run(host="0.0.0.0", port=port)
