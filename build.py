#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 抓 doraneko / doraneko2 (pictSPACE) + Fansky 三間店的商品清單，產生靜態 index.html。
#
# 封面圖策略（優先序）：
#   1. 用商品詳情頁裡的 pixiv 連結精準比對 Fansky 的同一作品封面（pixiv 網址相同 = 同一作品）
#   2. 比對不到 → 用商品名稱模糊比對 Fansky 商品取圖（容錯用，較不準）
#   3. 還是沒有（Fansky 根本沒賣這件，例如單人日記向商品）→ 用 pictSPACE 自己的原圖
#
# 價格：Fansky 的價格是登入後才用前端 JS 動態換算顯示，純 curl 抓不到，故不處理。
import re, os, subprocess, hashlib, base64, html, difflib, json
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, ".imgcache")
os.makedirs(CACHE, exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

STORES = [
    {"key": "doraneko", "label": "どらねこ", "kind": "pict", "url": "https://pictspace.net/stores/detail/doraneko"},
    {"key": "doraneko2", "label": "どらねこ2号店", "kind": "pict", "url": "https://pictspace.net/doraneko2"},
    {"key": "fansky", "label": "Fansky", "kind": "fansky", "url": "https://www.fansky.net/doraneko"},
]


def fetch(url, referer=None):
    cmd = ["curl", "-sL", "--max-time", "25", "-A", UA]
    if referer:
        cmd += ["-e", referer]
    cmd.append(url)
    return subprocess.check_output(cmd).decode("utf-8", "replace")


def extract_pixiv_id(url):
    try:
        text = fetch(url)
    except Exception:
        return None
    m = re.search(r"pixiv\.net/artworks/(\d+)", text)
    return m.group(1) if m else None


def fansky_items():
    out, page = [], 1
    while page <= 50:
        text = fetch("https://www.fansky.net/doraneko?page=%d" % page)
        blocks = text.split("fansky-1n4rs1i")[1:]
        if not blocks:
            break
        found = 0
        for b in blocks:
            m_title = re.search(r'<a title="([^"]+)"[^>]*href="([^"]+)"', b)
            m_img = re.search(r'<img[^>]*src="([^"]+)"', b)
            if not (m_title and m_img):
                continue
            out.append({
                "title": html.unescape(m_title.group(1)),
                "link": "https://www.fansky.net" + m_title.group(2),
                "img": m_img.group(1),
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
        if not (m_name and m_link):
            continue
        out.append({
            "title": html.unescape(m_name.group(1)),
            "link": "https://pictspace.net" + m_link.group(1),
            "native_img": m_img.group(1) if m_img else None,
        })
    return out


NOISE_WORDS = ["乱交パーティー", "大乱交", "パーティー", "とえっち", "えっち", "の3P!", "3P!"]


def core_name(title):
    name = title.split("(")[0].split("/")[0]
    for w in NOISE_WORDS:
        name = name.replace(w, "")
    name = name.replace("〇", "")
    return name.strip()


def fuzzy_match(title, fansky_name_index, threshold=0.38):
    target = core_name(title)
    if not target:
        return None
    best, best_score = None, 0.0
    for core, item in fansky_name_index:
        if not core:
            continue
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
        cmd.append(url)
        raw = subprocess.check_output(cmd)
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
    "ja": {"search": "検索...", "count": "件", "lang": "言語", "noimg": "画像なし"},
    "zh": {"search": "搜尋...", "count": "筆", "lang": "語言", "noimg": "無圖"},
    "en": {"search": "Search...", "count": "items", "lang": "Language", "noimg": "no image"},
}

TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title>shop list</title>
<style>
  body{font-family:'Segoe UI','Hiragino Kaku Gothic ProN','Microsoft JhengHei',sans-serif;margin:0;padding:1.2rem 1rem 3rem;background:#f4f4f8;color:#333;}
  .wrap{max-width:1200px;margin:0 auto;}
  .top{display:flex;justify-content:flex-end;gap:.4rem;margin-bottom:1rem;}
  .langbtn{border:1px solid #ccc;background:#fff;border-radius:8px;padding:.3rem .7rem;font-size:.78rem;cursor:pointer;}
  .langbtn.active{background:#e5507f;color:#fff;border-color:#e5507f;}
  section{margin-bottom:2.2rem;}
  h2{font-size:1.05rem;margin:0 0 .3rem;color:#d174a0;}
  .count{font-size:.78rem;color:#888;margin-bottom:.6rem;}
  .search{width:100%;max-width:320px;padding:.5rem .7rem;border:1px solid #ddd;border-radius:10px;font-size:.85rem;margin-bottom:.8rem;box-sizing:border-box;}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px;}
  .card{background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);text-decoration:none;color:inherit;display:block;}
  .card img{width:100%;aspect-ratio:1/1;object-fit:cover;display:block;background:#eee;}
  .noimg{width:100%;aspect-ratio:1/1;display:flex;align-items:center;justify-content:center;background:#eee;color:#aaa;font-size:.72rem;}
  .info{padding:.45rem .55rem;}
  .title{font-size:.74rem;line-height:1.3;height:2.6em;overflow:hidden;}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <button class="langbtn" data-lang="ja">日本語</button>
    <button class="langbtn" data-lang="zh">中文</button>
    <button class="langbtn" data-lang="en">English</button>
  </div>
  __SECTIONS__
</div>
<script>
var I18N = __I18N_JSON__;
function applyLang(lang){
  document.querySelectorAll('.search').forEach(function(el){ el.placeholder = I18N[lang].search; });
  document.querySelectorAll('.count').forEach(function(el){
    el.textContent = el.getAttribute('data-n') + ' ' + I18N[lang].count;
  });
  document.querySelectorAll('.noimg').forEach(function(el){ el.textContent = I18N[lang].noimg; });
  document.querySelectorAll('.langbtn').forEach(function(b){
    b.classList.toggle('active', b.getAttribute('data-lang') === lang);
  });
  try { localStorage.setItem('shoplang', lang); } catch(e){}
}
document.querySelectorAll('.langbtn').forEach(function(b){
  b.addEventListener('click', function(){ applyLang(b.getAttribute('data-lang')); });
});
document.querySelectorAll('.search').forEach(function(input){
  input.addEventListener('input', function(){
    var grid = document.getElementById(input.getAttribute('data-grid'));
    var q = input.value.trim().toLowerCase();
    grid.querySelectorAll('.card').forEach(function(card){
      var t = (card.getAttribute('data-title') || '').toLowerCase();
      card.style.display = (!q || t.indexOf(q) >= 0) ? '' : 'none';
    });
  });
});
var initial = 'ja';
try { initial = localStorage.getItem('shoplang') || 'ja'; } catch(e){}
applyLang(initial);
</script>
</body>
</html>"""


def render_section(store, items_with_cover):
    cards = []
    for it, img_url, referer in items_with_cover:
        title_attr = html.escape(it["title"])
        if img_url:
            img_data = thumb_b64(img_url, referer=referer)
            img_html = '<img src="%s" alt="" loading="lazy">' % img_data
        else:
            img_html = '<div class="noimg"></div>'
        cards.append(
            '<a class="card" data-title="%s" href="%s" target="_blank" rel="noopener">%s'
            '<div class="info"><div class="title">%s</div></div></a>'
            % (title_attr, html.escape(it["link"]), img_html, title_attr)
        )
    grid_id = "grid-%s" % store["key"]
    return (
        '<section>'
        '<h2>%s</h2>'
        '<div class="count" data-n="%d"></div>'
        '<input class="search" data-grid="%s" type="text">'
        '<div class="grid" id="%s">%s</div>'
        '</section>'
    ) % (html.escape(store["label"]), len(items_with_cover), grid_id, grid_id, "\n".join(cards))


if __name__ == "__main__":
    fansky_list = fansky_items()

    # 幫 Fansky 商品各自抓它詳情頁裡的 pixiv 連結（平行抓，加速）
    with ThreadPoolExecutor(max_workers=10) as ex:
        fansky_pixiv_ids = list(ex.map(lambda it: extract_pixiv_id(it["link"]), fansky_list))
    for it, pid in zip(fansky_list, fansky_pixiv_ids):
        it["pixiv_id"] = pid

    pixiv_index = {it["pixiv_id"]: it["img"] for it in fansky_list if it["pixiv_id"]}
    fansky_name_index = [(core_name(it["title"]), it) for it in fansky_list]

    sections_html = []
    counts = []
    for store in STORES:
        if store["kind"] == "fansky":
            items_with_cover = [(it, it["img"], None) for it in fansky_list]
        else:
            items = pict_items(store["url"])
            with ThreadPoolExecutor(max_workers=10) as ex:
                pict_pixiv_ids = list(ex.map(lambda it: extract_pixiv_id(it["link"]), items))
            items_with_cover = []
            for it, pid in zip(items, pict_pixiv_ids):
                if pid and pid in pixiv_index:
                    items_with_cover.append((it, pixiv_index[pid], None))
                else:
                    fuzzy = fuzzy_match(it["title"], fansky_name_index)
                    if fuzzy:
                        items_with_cover.append((it, fuzzy, None))
                    else:
                        items_with_cover.append((it, it.get("native_img"), "https://pictspace.net/"))
        sections_html.append(render_section(store, items_with_cover))
        counts.append("%s=%d" % (store["key"], len(items_with_cover)))

    out_html = TEMPLATE.replace("__SECTIONS__", "\n".join(sections_html)).replace(
        "__I18N_JSON__", json.dumps(I18N, ensure_ascii=False)
    )
    with open(os.path.join(BASE, "index.html"), "w", encoding="utf-8") as f:
        f.write(out_html)
    print("wrote sections: " + ", ".join(counts))
