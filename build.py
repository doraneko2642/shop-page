#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 抓 doraneko / doraneko2 (pictSPACE) + Fansky 三間店的商品，產生靜態 index.html（三欄並排）。
# 封面圖優先序：pixiv 連結相同的 Fansky 封面 → 名稱模糊比對 Fansky 封面 → pictSPACE 原圖
import re, os, subprocess, hashlib, base64, html, difflib, json
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, ".imgcache")
os.makedirs(CACHE, exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

STORES = [
    {"key": "doraneko", "label": "どらねこ", "site": "pictspace.net", "kind": "pict",
     "url": "https://pictspace.net/stores/detail/doraneko"},
    {"key": "doraneko2", "label": "どらねこ2号店", "site": "pictspace.net", "kind": "pict",
     "url": "https://pictspace.net/doraneko2"},
    {"key": "fansky", "label": "Fansky", "site": "fansky.net", "kind": "fansky",
     "url": "https://www.fansky.net/doraneko"},
]


def fetch(url):
    return subprocess.check_output(
        ["curl", "-sL", "--max-time", "25", "-A", UA, url]
    ).decode("utf-8", "replace")


def img_key(url):
    return url.split("/")[-1].split("?")[0]


FANSKY_META = re.compile(
    r'pixiv\.net/artworks/(\d+)'
    r'|\\"salesPrice\\":\\"([\d.]+)\\"'
    r'|\\"cover\\":\\"(https?://[^\\"]+)\\"'
)


def fansky_items():
    out, page = [], 1
    while page <= 50:
        text = fetch("https://www.fansky.net/doraneko?page=%d" % page)
        blocks = text.split("fansky-1n4rs1i")[1:]
        if not blocks:
            break
        # 頁面內嵌 JSON 的順序是：說明(含pixiv) → salesPrice → cover，用封面檔名對回卡片
        meta, cur_pixiv, cur_price = {}, None, None
        for m in FANSKY_META.finditer(text):
            if m.group(1):
                cur_pixiv = m.group(1)
            elif m.group(2):
                cur_price = m.group(2)
            else:
                meta[img_key(m.group(3))] = (cur_price, cur_pixiv)
                cur_pixiv = cur_price = None
        found = 0
        for b in blocks:
            m_title = re.search(r'<a title="([^"]+)"[^>]*href="([^"]+)"', b)
            m_img = re.search(r'<img[^>]*src="([^"]+)"', b)
            if not (m_title and m_img):
                continue
            img = html.unescape(m_img.group(1))
            price, pixiv = meta.get(img_key(img), (None, None))
            out.append({
                "title": html.unescape(m_title.group(1)),
                "link": "https://www.fansky.net" + m_title.group(2),
                "img": img,
                "price": ("CN¥" + price) if price else "",
                "pixiv": pixiv,
            })
            found += 1
        if found == 0:
            break
        page += 1
    return out


def pict_items(url):
    text = fetch(url)
    out = []
    for b in re.split(r"store-item-card", text)[1:]:
        m_name = re.search(r'data-item-keywords="([^"]*)"', b)
        m_link = re.search(r'data-action="([^"]+)"', b)
        m_img = re.search(r'<img src="([^"]+)"', b)
        m_price = re.search(r'([\d,]+)\s*円', b)
        if not (m_name and m_link):
            continue
        out.append({
            "title": html.unescape(m_name.group(1)),
            "link": "https://pictspace.net" + m_link.group(1),
            "native_img": m_img.group(1) if m_img else None,
            "price": ("¥" + m_price.group(1)) if m_price else "",
        })
    return out


def pixiv_id_of(url):
    try:
        m = re.search(r"pixiv\.net/artworks/(\d+)", fetch(url))
    except Exception:
        return None
    return m.group(1) if m else None


NOISE_WORDS = ["乱交パーティー", "大乱交", "パーティー", "とえっち", "えっち", "の3P!", "3P!"]


def core_name(title):
    name = title.split("(")[0].split("/")[0]
    for w in NOISE_WORDS:
        name = name.replace(w, "")
    return name.replace("〇", "").strip()


def fuzzy_match(title, name_index, threshold=0.38):
    target = core_name(title)
    if not target:
        return None
    best, best_score = None, 0.0
    for core, item in name_index:
        if core:
            score = difflib.SequenceMatcher(None, target, core).ratio()
            if score > best_score:
                best_score, best = score, item
    return best["img"] if best and best_score >= threshold else None


def thumb_b64(url, referer=None, width=320, q=6):
    key = hashlib.md5(url.encode()).hexdigest()
    out_path = os.path.join(CACHE, key + ".jpg")
    if not os.path.exists(out_path):
        cmd = ["curl", "-sL", "--max-time", "30", "-A", UA]
        if referer:
            cmd += ["-e", referer]
        raw = subprocess.check_output(cmd + [url])
        tmp = os.path.join(CACHE, key + ".src")
        with open(tmp, "wb") as f:
            f.write(raw)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", tmp,
             "-vf", "scale=%d:-1" % width, "-q:v", str(q), out_path],
            check=True,
        )
        try:
            os.unlink(tmp)
        except OSError:
            pass
    with open(out_path, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()


I18N = {
    "ja": {"heading": "商品一覧", "refresh": "再読み込み", "search": "検索...",
           "count": "件", "noimg": "画像なし", "cny": "人民元決済"},
    "zh": {"heading": "商品", "refresh": "重新整理", "search": "搜尋...",
           "count": "筆", "noimg": "無圖", "cny": "人民幣付款"},
    "en": {"heading": "Shop", "refresh": "Refresh", "search": "Search...",
           "count": "items", "noimg": "no image", "cny": "paid in CNY"},
}

TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title>shop list</title>
<style>
  :root{ --pink:#e5507f; --pink2:#d174a0; --blue:#8ab6ff; --text:#4a4a5c; }
  *{box-sizing:border-box;}
  body{font-family:'Segoe UI','Hiragino Kaku Gothic ProN','Yu Gothic','Microsoft JhengHei',sans-serif;
    margin:0;padding:1.2rem 1rem 2rem;min-height:100vh;color:var(--text);
    background:linear-gradient(135deg,#ffe3ee 0%,#e8e4ff 45%,#dcefff 100%);}
  .wrap{max-width:1280px;margin:0 auto;background:rgba(255,255,255,.85);border-radius:22px;
    box-shadow:0 18px 40px rgba(255,143,177,.28);padding:1.2rem 1.2rem 1.5rem;}
  .top{display:flex;justify-content:flex-end;gap:.4rem;}
  .langbtn{border:1px solid #ffd0e0;background:#fff;border-radius:8px;padding:.25rem .65rem;font-size:.75rem;cursor:pointer;color:var(--text);}
  .langbtn.active{background:var(--pink);color:#fff;border-color:var(--pink);}
  h1{text-align:center;color:var(--pink);font-size:1.25rem;margin:.2rem 0 .8rem;}
  .refresh{display:block;width:100%;border:none;border-radius:12px;padding:.6rem;font-size:.9rem;font-weight:700;
    color:#fff;background:linear-gradient(135deg,#9cc2ff,#7fb0ff);cursor:pointer;margin-bottom:1rem;}
  .stores{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;}
  @media(max-width:900px){ .stores{grid-template-columns:1fr;} }
  .col-head{font-weight:700;color:var(--pink2);font-size:.95rem;margin-bottom:.45rem;}
  .col-head a{color:var(--blue);font-weight:600;font-size:.8rem;text-decoration:none;}
  .col-head .note{font-weight:500;font-size:.78rem;}
  .count{font-weight:500;color:#999;font-size:.75rem;margin-left:.3rem;}
  .searchbox{position:relative;margin-bottom:.6rem;}
  .search{width:100%;padding:.55rem 2rem .55rem .8rem;border:2px solid #ffd0e0;border-radius:12px;font-size:.9rem;outline:none;background:#fff;}
  .search:focus{border-color:#ff9dbb;}
  .clear{position:absolute;right:.55rem;top:50%;transform:translateY(-50%);border:none;background:none;
    color:#7a8bb0;font-size:1rem;cursor:pointer;display:none;}
  .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:.6rem;max-height:75vh;overflow-y:auto;
    padding:.6rem;border:1px solid #ffe0ea;border-radius:14px;background:#fff8fb;align-content:start;}
  .card{background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 2px 6px rgba(0,0,0,.08);
    text-decoration:none;color:inherit;display:block;}
  .card img,.noimg{width:100%;aspect-ratio:1/1;object-fit:cover;display:block;background:#eee;}
  .noimg{display:flex;align-items:center;justify-content:center;color:#aaa;font-size:.7rem;}
  .info{padding:.35rem .45rem .45rem;}
  .title{font-size:.72rem;line-height:1.3;height:2.6em;overflow:hidden;}
  .price{font-size:.8rem;font-weight:700;color:var(--pink);margin-top:.2rem;}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <button class="langbtn" data-lang="ja">日本語</button>
    <button class="langbtn" data-lang="zh">中文</button>
    <button class="langbtn" data-lang="en">English</button>
  </div>
  <h1 data-i18n="heading"></h1>
  <button class="refresh" data-i18n="refresh"></button>
  <div class="stores">
  __SECTIONS__
  </div>
</div>
<script>
var I18N = __I18N_JSON__;
function applyLang(lang){
  document.querySelectorAll('[data-i18n]').forEach(function(el){ el.textContent = I18N[lang][el.getAttribute('data-i18n')]; });
  document.querySelectorAll('.search').forEach(function(el){ el.placeholder = I18N[lang].search; });
  document.querySelectorAll('.count').forEach(function(el){ el.textContent = el.getAttribute('data-n') + ' ' + I18N[lang].count; });
  document.querySelectorAll('.noimg').forEach(function(el){ el.textContent = I18N[lang].noimg; });
  document.querySelectorAll('.langbtn').forEach(function(b){ b.classList.toggle('active', b.getAttribute('data-lang') === lang); });
  try { localStorage.setItem('shoplang', lang); } catch(e){}
}
function filterGrid(input){
  var grid = document.getElementById(input.getAttribute('data-grid'));
  var q = input.value.trim().toLowerCase();
  input.parentNode.querySelector('.clear').style.display = q ? 'block' : 'none';
  grid.querySelectorAll('.card').forEach(function(card){
    var t = (card.getAttribute('data-title') || '').toLowerCase();
    card.style.display = (!q || t.indexOf(q) >= 0) ? '' : 'none';
  });
}
document.querySelectorAll('.langbtn').forEach(function(b){
  b.addEventListener('click', function(){ applyLang(b.getAttribute('data-lang')); });
});
document.querySelectorAll('.search').forEach(function(input){
  input.addEventListener('input', function(){ filterGrid(input); });
});
document.querySelectorAll('.clear').forEach(function(btn){
  btn.addEventListener('click', function(){
    var input = btn.parentNode.querySelector('.search');
    input.value = ''; filterGrid(input); input.focus();
  });
});
document.querySelector('.refresh').addEventListener('click', function(){
  location.replace(location.pathname + '?r=' + Date.now());
});
var initial = 'ja';
try { initial = localStorage.getItem('shoplang') || 'ja'; } catch(e){}
applyLang(initial);
</script>
</body>
</html>"""


def render_section(store, rows):
    cards = []
    for it, img_url, referer in rows:
        t = html.escape(it["title"])
        if img_url:
            img_html = '<img src="%s" alt="" loading="lazy">' % thumb_b64(img_url, referer=referer)
        else:
            img_html = '<div class="noimg"></div>'
        price_html = '<div class="price">%s</div>' % html.escape(it["price"]) if it.get("price") else ""
        cards.append(
            '<a class="card" data-title="%s" href="%s" target="_blank" rel="noopener">%s'
            '<div class="info"><div class="title">%s</div>%s</div></a>'
            % (t, html.escape(it["link"]), img_html, t, price_html)
        )
    note = ' <span class="note">（<span data-i18n="cny"></span>）</span>' if store["kind"] == "fansky" else ""
    grid_id = "grid-%s" % store["key"]
    return (
        '<div class="col">'
        '<div class="col-head">%s%s・<a href="%s" target="_blank" rel="noopener">%s</a>'
        '<span class="count" data-n="%d"></span></div>'
        '<div class="searchbox"><input class="search" data-grid="%s" type="text">'
        '<button class="clear" type="button">✕</button></div>'
        '<div class="grid" id="%s">%s</div>'
        '</div>'
    ) % (html.escape(store["label"]), note, store["url"], store["site"], len(rows),
         grid_id, grid_id, "\n".join(cards))


if __name__ == "__main__":
    fansky_list = fansky_items()
    pixiv_index = {it["pixiv"]: it["img"] for it in fansky_list if it["pixiv"]}
    name_index = [(core_name(it["title"]), it) for it in fansky_list]

    sections, counts = [], []
    for store in STORES:
        if store["kind"] == "fansky":
            rows = [(it, it["img"], None) for it in fansky_list]
        else:
            items = pict_items(store["url"])
            with ThreadPoolExecutor(max_workers=8) as ex:
                pids = list(ex.map(lambda it: pixiv_id_of(it["link"]), items))
            rows = []
            for it, pid in zip(items, pids):
                cover = pixiv_index.get(pid) if pid else None
                if not cover:
                    cover = fuzzy_match(it["title"], name_index)
                if cover:
                    rows.append((it, cover, None))
                else:
                    rows.append((it, it["native_img"], "https://pictspace.net/"))
        sections.append(render_section(store, rows))
        counts.append("%s=%d" % (store["key"], len(rows)))

    out_html = TEMPLATE.replace("__SECTIONS__", "\n".join(sections)).replace(
        "__I18N_JSON__", json.dumps(I18N, ensure_ascii=False))
    with open(os.path.join(BASE, "index.html"), "w", encoding="utf-8") as f:
        f.write(out_html)
    print("wrote: " + ", ".join(counts))
