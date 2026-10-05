#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 從 Fansky 商店頁抓全部商品（標題/價格/封面圖/連結），產生靜態 index.html
import re, os, subprocess, hashlib, base64, html

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, ".imgcache")
os.makedirs(CACHE, exist_ok=True)

STORE_URL = "https://www.fansky.net/doraneko"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def fetch(url):
    return subprocess.check_output(
        ["curl", "-sL", "--max-time", "30", "-A", UA, url]
    ).decode("utf-8", "replace")


def fansky_items():
    out, page = [], 1
    while page <= 50:
        text = fetch("%s?page=%d" % (STORE_URL, page))
        blocks = text.split("fansky-1n4rs1i")[1:]
        if not blocks:
            break
        found = 0
        for b in blocks:
            m_title = re.search(r'<a title="([^"]+)"[^>]*href="([^"]+)"', b)
            m_img = re.search(r'<img[^>]*src="([^"]+)"', b)
            m_price = re.search(r">([¥$][\d,.]+)</h6>", b)
            if not (m_title and m_img):
                continue
            out.append({
                "title": html.unescape(m_title.group(1)),
                "link": "https://www.fansky.net" + m_title.group(2),
                "img": m_img.group(1),
                "price": m_price.group(1) if m_price else "",
            })
            found += 1
        if found == 0:
            break
        page += 1
    return out


def thumb_b64(url, width=320, q=6):
    key = hashlib.md5(url.encode()).hexdigest()
    out_path = os.path.join(CACHE, key + ".jpg")
    if not os.path.exists(out_path):
        raw = subprocess.check_output(["curl", "-sL", "--max-time", "30", "-A", UA, url])
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


TEMPLATE = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title>shop list</title>
<style>
  body{font-family:'Segoe UI','Microsoft JhengHei',sans-serif;margin:0;padding:1.5rem 1rem;background:#f4f4f8;color:#333;}
  .wrap{max-width:1100px;margin:0 auto;}
  h1{font-size:1.2rem;text-align:center;}
  .count{text-align:center;color:#888;font-size:.8rem;margin-bottom:1.2rem;}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:14px;}
  .card{background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);text-decoration:none;color:inherit;display:block;}
  .card img{width:100%;aspect-ratio:1/1;object-fit:cover;display:block;}
  .info{padding:.5rem .6rem;}
  .title{font-size:.76rem;line-height:1.3;height:2.6em;overflow:hidden;}
  .price{font-size:.85rem;font-weight:700;color:#e5507f;margin-top:.3rem;}
</style>
</head>
<body>
<div class="wrap">
  <h1>商品一覽</h1>
  <div class="count">共 __COUNT__ 筆・自動更新</div>
  <div class="grid">
  __CARDS__
  </div>
</div>
</body>
</html>"""


def build_html(items):
    cards = []
    for it in items:
        img_data = thumb_b64(it["img"])
        cards.append(
            '<a class="card" href="%s" target="_blank" rel="noopener">'
            '<img src="%s" alt="" loading="lazy">'
            '<div class="info"><div class="title">%s</div>'
            '<div class="price">%s</div></div></a>'
            % (html.escape(it["link"]), img_data, html.escape(it["title"]), html.escape(it["price"]))
        )
    return TEMPLATE.replace("__CARDS__", "\n".join(cards)).replace("__COUNT__", str(len(items)))


if __name__ == "__main__":
    items = fansky_items()
    out_html = build_html(items)
    with open(os.path.join(BASE, "index.html"), "w", encoding="utf-8") as f:
        f.write(out_html)
    print("wrote %d items" % len(items))
