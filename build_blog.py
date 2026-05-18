#!/usr/bin/env python3
"""Kゼミ ブログ ワンクリックビルド
posts/*.md を読み取り → 各記事HTML + ブログインデックスを再生成
依存: 標準ライブラリのみ"""
import os, re, sys, glob, base64, datetime, html as html_lib

BASE = os.path.dirname(os.path.abspath(__file__))
POSTS_DIR = os.path.join(BASE, "posts")
DIST_DIR = os.path.join(BASE, "dist")
IMG_DIR_LOCAL = os.path.join(BASE, "images")
IMG_DIR_GLOBAL = os.path.expanduser("~/edushift-hp-builder/assets/kzemi")

SCHOOL_NAME = "個別指導塾 Kゼミ"
EMAIL = "nakano@kzemi.com"
ADDRESS = "〒164-0001 東京都中野区中野2-12-12 中野オクト勧業ビル2F"

V = {
    "primary": "#1B5E20",
    "primary_light": "#E8F5E9",
    "primary_dark": "#0D3311",
    "accent": "#C9A227",
    "accent_hover": "#B0891C",
    "hero_overlay": "linear-gradient(135deg, rgba(13,51,17,0.84) 0%, rgba(27,94,32,0.78) 50%, rgba(13,51,17,0.74) 100%)",
}

def read_b64(name):
    for d in (IMG_DIR_LOCAL, IMG_DIR_GLOBAL):
        path = os.path.join(d, f"{name}.b64")
        if os.path.exists(path):
            with open(path) as f:
                return f.read().strip()
    return ""


# ============================================================
# Markdown 解析
# ============================================================
def parse_frontmatter(text):
    """YAMLライクなフロントマターをdictに"""
    m = re.match(r'^---\n(.*?)\n---\n(.*)$', text, re.DOTALL)
    if not m:
        return {}, text
    fm_text, body = m.group(1), m.group(2).lstrip()
    fm = {}
    for line in fm_text.split('\n'):
        if ':' in line:
            k, _, v = line.partition(':')
            fm[k.strip()] = v.strip()
    return fm, body


def inline(text):
    """**bold** ==marker== [text](url) ![alt](img) を変換。HTMLエスケープは行わない（既存HTML対応）"""
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'==(.+?)==', r'<span class="marker">\1</span>', text)
    # 画像（リンクより前に処理。!付きパターンが先にマッチするため）
    text = re.sub(r'!\[(.*?)\]\((.+?)\)', r'<img src="\2" alt="\1" loading="lazy" class="post-img">', text)
    text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2" target="_blank" rel="noopener">\1</a>', text)
    return text


def parse_blocks(body):
    """本文をブロックに分割"""
    blocks = []
    lines = body.split('\n')
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        # 空行スキップ
        if not line.strip():
            i += 1
            continue
        # h2
        if line.startswith('## '):
            blocks.append({"type": "h2", "text": inline(line[3:].strip())})
            i += 1
            continue
        # h3
        if line.startswith('### '):
            blocks.append({"type": "h3", "text": inline(line[4:].strip())})
            i += 1
            continue
        # callout: ::: callout タイトル
        m = re.match(r'^::: callout\s+(.+)$', line)
        if m:
            title = m.group(1).strip()
            j = i + 1
            inner = []
            while j < n and not lines[j].strip().startswith(':::'):
                inner.append(lines[j])
                j += 1
            i = j + 1
            # innerを 1. 2. のリストとそれ以外のpに分離
            items = []
            text_lines = []
            for ln in inner:
                m2 = re.match(r'^\s*\d+\.\s+(.+)$', ln)
                if m2:
                    items.append(inline(m2.group(1).strip()))
                elif ln.strip():
                    text_lines.append(inline(ln.strip()))
            blocks.append({"type": "callout", "title": title, "text": " ".join(text_lines), "items": items})
            continue
        # blockquote
        if line.startswith('>'):
            quote_lines = []
            author = ""
            while i < n and lines[i].startswith('>'):
                content = lines[i][1:].lstrip()
                m2 = re.match(r'^--\s+(.+)$', content)
                if m2:
                    author = m2.group(1).strip()
                else:
                    quote_lines.append(content)
                i += 1
            blocks.append({"type": "quote", "text": inline(" ".join(quote_lines).strip()), "by": author})
            continue
        # list
        if line.startswith('- '):
            items = []
            while i < n and lines[i].startswith('- '):
                items.append(inline(lines[i][2:].strip()))
                i += 1
            blocks.append({"type": "list", "items": items})
            continue
        # paragraph: continue until blank line
        para_lines = []
        while i < n and lines[i].strip() and not lines[i].startswith(('## ', '### ', '- ', '> ', ':::')):
            para_lines.append(lines[i].strip())
            i += 1
        if para_lines:
            blocks.append({"type": "p", "text": inline(" ".join(para_lines))})
    return blocks


def render_blocks(blocks, lead_used=False):
    """Block dict のリストをHTMLに。最初のpはleadとして特別扱い"""
    html = []
    first_p_done = lead_used
    for b in blocks:
        t = b["type"]
        if t == "p":
            if not first_p_done:
                html.append(f'<p class="post-lead">{b["text"]}</p>')
                first_p_done = True
            else:
                html.append(f'<p class="post-p">{b["text"]}</p>')
        elif t == "h2":
            html.append(f'<h2 class="post-h2">{b["text"]}</h2>')
        elif t == "h3":
            html.append(f'<h3 class="post-h3">{b["text"]}</h3>')
        elif t == "list":
            items = "\n".join(f'<li>{x}</li>' for x in b["items"])
            html.append(f'<ul class="post-list">\n{items}\n</ul>')
        elif t == "quote":
            by = f'<cite class="post-quote-by">— {b["by"]}</cite>' if b.get("by") else ""
            html.append(f'<blockquote class="post-quote"><p>{b["text"]}</p>{by}</blockquote>')
        elif t == "callout":
            items = "\n".join(f'<li>{x}</li>' for x in b.get("items", []))
            text = f'<p>{b["text"]}</p>' if b.get("text") else ""
            list_html = f'<ol class="post-callout-list">\n{items}\n</ol>' if items else ""
            html.append(f'<aside class="post-callout"><h4>{b["title"]}</h4>{text}{list_html}</aside>')
    return "\n".join(html)


# ============================================================
# 共通CSS / Header / Footer
# ============================================================
def common_css():
    return f"""
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html{{scroll-behavior:smooth}}
body{{font-family:'Noto Sans JP',sans-serif;color:#2D3748;background:#fff;line-height:1.8;-webkit-font-smoothing:antialiased;overflow-x:hidden}}
img{{max-width:100%;height:auto;display:block}}
.post-img{{max-width:100%;height:auto;display:block;margin:32px auto;border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,.08)}}
a{{color:inherit;text-decoration:none}}
ul,ol{{list-style:none}}

:root{{
  --primary:{V["primary"]};
  --primary-light:{V["primary_light"]};
  --primary-dark:{V["primary_dark"]};
  --accent:{V["accent"]};
  --accent-hover:{V["accent_hover"]};
  --text:#2D3748;
  --text-light:#718096;
}}

h1,h2,h3,h4{{font-family:'Noto Serif JP',serif;font-weight:800;line-height:1.4}}

.header{{position:sticky;top:0;left:0;right:0;background:#fff;z-index:1000;transition:box-shadow .3s}}
.header.scrolled{{box-shadow:0 4px 20px rgba(0,0,0,.06)}}
.header-top{{border-bottom:3px solid var(--primary)}}
.header-inner{{max-width:1280px;margin:0 auto;padding:14px 1.5rem;display:flex;align-items:center;justify-content:space-between;gap:1.5rem}}
.header-logo{{display:flex;flex-direction:column;align-items:flex-start}}
.logo-sub{{font-size:.78rem;color:var(--text-light);letter-spacing:.05em;font-weight:500}}
.logo-main{{font-family:'Noto Serif JP',serif;font-size:1.6rem;font-weight:900;color:var(--primary);line-height:1.2}}
.header-tagline{{font-family:'Noto Serif JP',serif;font-size:.95rem;color:var(--primary-dark);font-weight:600;letter-spacing:.05em;align-self:center;padding:0 1.5rem;border-left:2px solid var(--primary-light);border-right:2px solid var(--primary-light);margin:0 auto}}
.header-cta-btn{{background:var(--accent);color:#fff;padding:16px 32px;border-radius:60px;font-weight:700;font-size:.95rem;display:flex;align-items:center;gap:8px;white-space:nowrap;transition:background .2s,transform .2s;box-shadow:0 4px 16px rgba(201,162,39,.32)}}
.header-cta-btn:hover{{background:var(--accent-hover);transform:translateY(-2px)}}
.main-nav{{background:var(--primary);padding:0}}
.main-nav ul{{display:flex;justify-content:center;gap:0;max-width:1280px;margin:0 auto}}
.main-nav li{{flex:1}}
.main-nav a{{display:block;padding:14px 12px;color:#fff;font-weight:600;font-size:.92rem;text-align:center;transition:background .2s}}
.main-nav a:hover,.main-nav a.active{{background:var(--primary-dark)}}
.hamburger{{display:none}}
@media(max-width:768px){{
  .header-inner{{padding:12px 1rem;gap:.5rem}}
  .header-tagline,.header-cta-btn{{display:none}}
  .hamburger{{display:flex;flex-direction:column;gap:5px;border:none;background:transparent;cursor:pointer;padding:8px;width:44px;height:44px;justify-content:center;align-items:center;margin-left:auto}}
  .hamburger span{{display:block;width:24px;height:2.5px;background:var(--primary);transition:transform .3s,opacity .3s}}
  .main-nav{{position:absolute;top:100%;left:0;right:0;max-height:0;overflow:hidden;transition:max-height .3s}}
  .main-nav.open{{max-height:600px}}
  .main-nav ul{{flex-direction:column;padding:1rem 0}}
  .main-nav li{{flex:none}}
}}

footer{{background:var(--primary);color:#fff;padding:48px 1.5rem;text-align:center}}
footer p{{font-size:.85rem;opacity:.6;margin-top:8px}}

.floating-cta{{position:fixed;bottom:24px;right:24px;z-index:999}}
.floating-cta a{{width:64px;height:64px;border-radius:50%;display:flex;align-items:center;justify-content:center;box-shadow:0 6px 24px rgba(0,0,0,.22);transition:transform .2s;background:linear-gradient(135deg,var(--primary),var(--primary-dark));color:#fff}}
.floating-cta a:hover{{transform:scale(1.08)}}
.scroll-progress{{position:fixed;top:0;left:0;height:3px;background:linear-gradient(90deg,var(--accent),var(--primary));z-index:1001;width:0%;transition:width .1s}}
"""


def header_html(blog_active=False, depth=0):
    """depth: 0=ブログ, 1=記事個別ページ"""
    prefix = "../index.html" if depth == 0 else "../../index.html"
    blog_link = "./index.html" if depth == 0 else "../index.html"
    blog_class = ' class="active"' if blog_active else ""
    return f"""
<header class="header" id="header">
  <div class="header-top">
    <div class="header-inner">
      <div class="header-logo">
        <span class="logo-sub">中野駅南口 徒歩5分 / 開校30年</span>
        <span class="logo-main">{SCHOOL_NAME}</span>
      </div>
      <div class="header-tagline">
        <span>自ら解決する力を身に着ける</span>
      </div>
      <a href="{prefix}#contact-form" class="header-cta-btn">無料体験授業に申し込む <span>&#10132;</span></a>
      <button class="hamburger" id="hamburger" aria-label="メニュー"><span></span><span></span><span></span></button>
    </div>
  </div>
  <nav class="main-nav" id="mainNav">
    <ul>
      <li><a href="{blog_link}"{blog_class}>お知らせ・ブログ</a></li>
      <li><a href="{prefix}#features">特徴</a></li>
      <li><a href="{prefix}#tuition">料金</a></li>
      <li><a href="{prefix}#instructor">塾長あいさつ</a></li>
      <li><a href="{prefix}#cap">CAP</a></li>
      <li><a href="{prefix}#access">アクセス</a></li>
      <li><a href="{prefix}#contact-form">無料体験申込</a></li>
    </ul>
  </nav>
</header>
"""


def footer_html():
    return f"""
<footer>
  <div>
    <p style="font-family:'Noto Serif JP',serif;font-size:1.2rem;font-weight:700">{SCHOOL_NAME} 中野校</p>
    <p>{ADDRESS}</p>
    <p>営業時間 13:00~20:00 / 日曜定休</p>
    <p style="margin-top:1rem;font-size:.8rem;opacity:.4">&copy; 2026 {SCHOOL_NAME}</p>
  </div>
</footer>
"""


def floating_cta(depth=0):
    href = "../index.html#contact-form" if depth == 0 else "../../index.html#contact-form"
    return f"""
<div class="floating-cta">
  <a href="{href}" aria-label="無料体験を申し込む">
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
  </a>
</div>
<script>
window.addEventListener('scroll',()=>{{
  const p=document.getElementById('scrollProgress');
  const s=window.scrollY/(document.documentElement.scrollHeight-window.innerHeight)*100;
  p.style.width=s+'%';
}});
window.addEventListener('scroll',()=>{{
  document.getElementById('header').classList.toggle('scrolled',window.scrollY>50);
}});
const hb=document.getElementById('hamburger'),nav=document.getElementById('mainNav');
hb.addEventListener('click',()=>{{hb.classList.toggle('open');nav.classList.toggle('open')}});
</script>
"""


# ============================================================
# 記事ページ生成
# ============================================================
POST_PAGE_CSS = """
.post-hero{position:relative;min-height:42vh;display:flex;align-items:flex-end;overflow:hidden}
.post-hero-bg{position:absolute;inset:0;z-index:0}
.post-hero-bg img{width:100%;height:100%;object-fit:cover;object-position:65% 35%}
.post-hero-overlay{position:absolute;inset:0;background:HERO_OVERLAY;z-index:1}
.post-hero-content{position:relative;z-index:2;max-width:min(1100px,90vw);margin:0 auto;padding:5rem 1.5rem 3.5rem;color:#fff;width:100%}
.breadcrumb{font-size:.85rem;opacity:.85;margin-bottom:1.25rem}
.breadcrumb a{color:#FFD580;text-decoration:underline;text-decoration-color:rgba(255,213,128,.35);text-underline-offset:3px}
.post-hero-meta{display:flex;align-items:center;gap:14px;margin-bottom:1rem;flex-wrap:wrap}
.post-category-badge{font-size:.78rem;font-weight:700;padding:5px 16px;border-radius:30px;background:#fff;letter-spacing:.05em}
.post-date{font-size:.85rem;opacity:.85;font-weight:500}
.post-read-time{font-size:.85rem;opacity:.7}
.post-hero h1{font-family:'Noto Serif JP',serif;font-size:clamp(1.7rem,3.4vw,2.6rem);font-weight:900;line-height:1.5;margin-bottom:0;text-shadow:0 4px 24px rgba(0,0,0,.3)}
.post-section{padding:64px 1.5rem 80px;background:#fff}
.post-container{max-width:780px;margin:0 auto}
.post-lead{font-family:'Noto Serif JP',serif;font-size:1.18rem;line-height:2.1;color:var(--primary-dark);margin-bottom:3rem;padding:24px 28px;background:linear-gradient(135deg,#f6fbf7,#eaf5ec);border-left:5px solid var(--primary);border-radius:6px}
.post-h2{font-size:clamp(1.5rem,2.5vw,1.85rem);color:var(--primary-dark);margin:3.5rem 0 1.5rem;padding-bottom:.65rem;border-bottom:3px double rgba(27,94,32,.25);position:relative}
.post-h2::before{content:'';position:absolute;left:0;bottom:-6px;width:80px;height:3px;background:var(--accent);border-radius:2px}
.post-h3{font-size:1.22rem;color:var(--primary);margin:2.4rem 0 1rem;padding-left:14px;border-left:5px solid var(--accent)}
.post-p{font-size:1rem;line-height:2.05;color:var(--text);margin-bottom:1.4rem}
.post-p .marker,.post-list .marker{background:linear-gradient(transparent 60%,rgba(201,162,39,.40) 60%);padding:0 2px}
.post-p strong,.post-list strong{color:var(--primary-dark);font-weight:700}
.post-list{margin:1.5rem 0 2rem;padding:0}
.post-list li{position:relative;padding:8px 0 8px 32px;font-size:.98rem;line-height:1.85;border-bottom:1px dashed rgba(27,94,32,.15)}
.post-list li::before{content:'';position:absolute;left:8px;top:18px;width:8px;height:8px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 3px rgba(201,162,39,.18)}
.post-quote{margin:2.5rem 0;padding:32px 36px;background:linear-gradient(135deg,#fffaf0,#fef5e0);border-radius:10px;border-left:5px solid var(--accent);position:relative;font-family:'Klee One',serif}
.post-quote::before{content:'\\201C';position:absolute;top:8px;left:14px;font-family:'Noto Serif JP',serif;font-size:4rem;color:var(--accent);opacity:.45;line-height:1}
.post-quote p{font-size:1.02rem;line-height:2;color:#3a2e1a;text-indent:1.2em;margin-bottom:0}
.post-quote-by{display:block;text-align:right;font-size:.88rem;color:var(--primary-dark);margin-top:1rem;font-weight:600;font-style:normal}
.post-callout{margin:2.5rem 0;padding:28px 30px;background:#f0faf2;border:1.5px solid rgba(27,94,32,.18);border-radius:12px}
.post-callout h4{font-size:1.08rem;color:var(--primary-dark);margin-bottom:1rem;display:flex;align-items:center;gap:10px}
.post-callout h4::before{content:'';width:8px;height:24px;background:var(--accent);border-radius:2px}
.post-callout p{font-size:.95rem;color:var(--text);line-height:1.95;margin-bottom:1rem}
.post-callout-list{margin:0;padding:0;counter-reset:c}
.post-callout-list li{position:relative;padding:10px 0 10px 44px;font-size:.95rem;counter-increment:c}
.post-callout-list li::before{content:counter(c);position:absolute;left:0;top:8px;width:30px;height:30px;border-radius:50%;background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center;font-size:.85rem;font-weight:700;font-family:'Noto Serif JP',serif}
.post-tags{margin:3rem 0 0;padding:1.5rem 0;border-top:1px solid #e2e8f0;display:flex;flex-wrap:wrap;gap:8px}
.post-tag{display:inline-block;padding:6px 14px;font-size:.82rem;color:var(--primary-dark);background:#f0faf2;border-radius:30px;border:1px solid rgba(27,94,32,.15);font-weight:500}
.post-share{margin:2rem 0;padding:24px;background:#fafdfb;border-radius:12px;text-align:center}
.post-share-label{font-size:.85rem;color:var(--text-light);font-weight:600;margin-bottom:1rem;letter-spacing:.05em}
.post-share-buttons{display:flex;justify-content:center;gap:12px;flex-wrap:wrap}
.share-btn{display:flex;align-items:center;gap:8px;padding:10px 22px;border-radius:30px;font-size:.85rem;font-weight:600;color:#fff;transition:transform .2s,box-shadow .2s}
.share-btn:hover{transform:translateY(-2px);box-shadow:0 4px 16px rgba(0,0,0,.12)}
.share-x{background:#000}.share-fb{background:#1877F2}.share-line{background:#06C755}
.post-cta-block{margin:3.5rem 0 2rem;padding:36px 32px;background:linear-gradient(135deg,var(--primary),var(--primary-dark));border-radius:16px;color:#fff;text-align:center}
.post-cta-block h3{font-size:1.3rem;margin-bottom:.75rem;color:#fff}
.post-cta-block p{font-size:.95rem;opacity:.92;margin-bottom:1.5rem;line-height:1.85}
.post-cta-btn{display:inline-block;background:linear-gradient(135deg,var(--accent),var(--accent-hover));color:#fff;padding:14px 36px;border-radius:50px;font-weight:700;font-size:1rem;box-shadow:0 4px 16px rgba(201,162,39,.42)}
.post-cta-btn:hover{transform:translateY(-2px)}
.related-section{padding:60px 1.5rem;background:linear-gradient(180deg,#f0faf2 0%,#fafdfb 100%)}
.related-container{max-width:1100px;margin:0 auto}
.related-section-head{text-align:center;margin-bottom:2.5rem}
.related-label{display:inline-block;font-size:.75rem;font-weight:700;letter-spacing:.15em;color:var(--accent);margin-bottom:.5rem}
.related-title{font-size:1.6rem;color:var(--primary-dark)}
.related-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px}
.related-card{background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 4px 20px rgba(13,51,17,.06);transition:transform .2s,box-shadow .2s;display:flex;flex-direction:column}
.related-card:hover{transform:translateY(-4px);box-shadow:0 12px 32px rgba(13,51,17,.10)}
.related-thumb{aspect-ratio:16/9;display:flex;align-items:center;justify-content:center;color:#fff;font-family:'Noto Serif JP',serif;font-weight:900;font-size:1.1rem;letter-spacing:.05em}
.related-body{padding:18px 20px}
.related-body h4{font-family:'Noto Serif JP',serif;font-size:.98rem;line-height:1.6;color:var(--primary-dark);margin-bottom:8px}
.related-date{font-size:.78rem;color:var(--text-light)}
.back-block{text-align:center;margin:2.5rem 0 0}
.back-block a{display:inline-block;padding:14px 32px;border-radius:50px;background:linear-gradient(135deg,var(--primary),var(--primary-dark));color:#fff;font-weight:600;font-size:.95rem;box-shadow:0 4px 16px rgba(13,51,17,.18)}
@media(max-width:768px){
  .post-section{padding:44px 1rem 60px}
  .post-lead{padding:18px 20px;font-size:1rem}
  .post-callout,.post-quote{padding:20px 22px}
}
"""


def render_post_page(post, related_posts):
    """1記事のHTMLを生成"""
    fm = post["fm"]
    blocks = post["blocks"]
    body_html = render_blocks(blocks)
    hero_b64 = read_b64("blog-hero") or read_b64("hero")
    hero_img = f'data:image/jpeg;base64,{hero_b64}' if hero_b64 else ""
    cat_color = fm.get("category_color", "#1B5E20")
    tags = [t.strip() for t in fm.get("tags", "").split(",") if t.strip()]
    tags_html = "\n".join(f'<span class="post-tag">#{t}</span>' for t in tags)
    related_cards = []
    for r in related_posts[:3]:
        rfm = r["fm"]
        rcolor = rfm.get("category_color", "#1B5E20")
        rslug = rfm.get("slug", "")
        related_cards.append(f"""
        <a href="../{rslug}/index.html" class="related-card">
          <div class="related-thumb" style="background:linear-gradient(135deg,{rcolor},{rcolor}cc)">
            <span>{rfm.get("category","")}</span>
          </div>
          <div class="related-body">
            <h4>{rfm.get("title","")}</h4>
            <span class="related-date">{rfm.get("date","")}</span>
          </div>
        </a>""")
    related_html = "\n".join(related_cards) if related_cards else '<p style="text-align:center;color:var(--text-light)">他の記事は順次公開予定です。</p>'
    css = (common_css() + POST_PAGE_CSS).replace("HERO_OVERLAY", V["hero_overlay"])
    title = fm.get("title", "")
    lead_for_meta = ""
    for b in blocks:
        if b["type"] == "p":
            lead_for_meta = re.sub(r'<[^>]+>', '', b["text"])[:120]
            break

    page = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}｜{SCHOOL_NAME} 中野校</title>
<meta name="description" content="{lead_for_meta}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{lead_for_meta}">
<meta property="og:type" content="article">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Klee+One:wght@400;600&family=Noto+Sans+JP:wght@400;500;700;900&family=Noto+Serif+JP:wght@500;700;900&display=swap" rel="stylesheet">
<style>{css}</style>
</head>
<body>
<div class="scroll-progress" id="scrollProgress"></div>
{header_html(blog_active=True, depth=1)}
<section class="post-hero">
  <div class="post-hero-bg"><img src="{hero_img}" alt="{title}"></div>
  <div class="post-hero-overlay"></div>
  <div class="post-hero-content">
    <div class="breadcrumb">
      <a href="../../index.html">ホーム</a>　&gt;　<a href="../index.html">お知らせ・ブログ</a>　&gt;　{fm.get("category","")}
    </div>
    <div class="post-hero-meta">
      <span class="post-category-badge" style="color:{cat_color}">{fm.get("category","")}</span>
      <span class="post-date">{fm.get("date","")}</span>
      <span class="post-read-time">読了 {fm.get("read_time","約5分")}</span>
    </div>
    <h1>{title}</h1>
  </div>
</section>
<section class="post-section">
  <article class="post-container">
{body_html}
    <div class="post-cta-block">
      <h3>無料体験授業 受付中</h3>
      <p>記事をお読みいただきありがとうございました。<br>Kゼミ中野校では、随時無料体験授業を実施しています。お気軽にお申込みください。</p>
      <a href="../../index.html#contact-form" class="post-cta-btn">無料体験を申し込む &#10132;</a>
    </div>
    <div class="post-tags">
{tags_html}
    </div>
    <div class="post-share">
      <div class="post-share-label">この記事をシェアする</div>
      <div class="post-share-buttons">
        <a class="share-btn share-x" href="https://twitter.com/intent/tweet?text={html_lib.escape(title)}" target="_blank" rel="noopener">X (Twitter)</a>
        <a class="share-btn share-fb" href="https://www.facebook.com/sharer/sharer.php" target="_blank" rel="noopener">Facebook</a>
        <a class="share-btn share-line" href="https://social-plugins.line.me/lineit/share" target="_blank" rel="noopener">LINE</a>
      </div>
    </div>
  </article>
</section>
<section class="related-section">
  <div class="related-container">
    <div class="related-section-head">
      <div class="related-label">RELATED POSTS</div>
      <h2 class="related-title">関連記事</h2>
    </div>
    <div class="related-grid">
{related_html}
    </div>
    <div class="back-block">
      <a href="../index.html">&#10132; ブログ一覧に戻る</a>
    </div>
  </div>
</section>
{footer_html()}
{floating_cta(depth=1)}
</body>
</html>"""
    return page


# ============================================================
# ブログインデックス生成
# ============================================================
INDEX_PAGE_CSS = """
.blog-hero{position:relative;min-height:62vh;display:flex;align-items:center;overflow:hidden;background:#0D3311}
.blog-hero-bg{position:absolute;inset:0;z-index:0}
.blog-hero-bg img{width:100%;height:100%;object-fit:cover;object-position:50% 28%;transform:scale(0.92);transform-origin:center}
.blog-hero-overlay{position:absolute;inset:0;background:HERO_OVERLAY;z-index:1}
.blog-hero-content{position:relative;z-index:2;max-width:min(1200px,90vw);margin:0 auto;padding:6rem 1.5rem 4rem;color:#fff;width:100%}
.blog-hero-label{display:inline-block;font-size:.78rem;font-weight:700;letter-spacing:.25em;text-transform:uppercase;color:#FFD580;margin-bottom:.75rem}
.blog-hero h1{font-family:'Noto Serif JP',serif;font-size:clamp(2.2rem,5vw,3.6rem);font-weight:900;letter-spacing:.05em;margin-bottom:1rem;text-shadow:0 4px 30px rgba(0,0,0,.3)}
.blog-hero p{font-size:clamp(.95rem,1.5vw,1.1rem);opacity:.92;max-width:680px;line-height:1.9}
.breadcrumb{font-size:.85rem;opacity:.85;margin-top:1.5rem}
.breadcrumb a{color:#FFD580;text-decoration:underline}
.blog-section{padding:80px 1.5rem;position:relative;overflow:hidden;background:linear-gradient(180deg,#fafdfb 0%,#f0faf2 100%)}
.watermark{position:absolute;font-size:10rem;font-weight:900;opacity:.04;color:var(--primary);pointer-events:none;white-space:nowrap;font-family:'Noto Serif JP',serif;z-index:0;top:-20px;left:-40px}
.blog-container{max-width:1180px;margin:0 auto;position:relative;z-index:1}
.blog-section-head{text-align:center;margin-bottom:3rem}
.blog-section-label{display:inline-block;font-size:.75rem;font-weight:700;letter-spacing:.15em;text-transform:uppercase;color:var(--accent);margin-bottom:.5rem}
.blog-section-title{font-size:clamp(1.6rem,3vw,2.2rem);color:var(--primary-dark);margin-bottom:.75rem;font-weight:800}
.blog-section-title::after{content:'';display:block;width:60px;height:4px;background:var(--accent);margin:16px auto 0;border-radius:2px}
.blog-section-desc{font-size:.98rem;color:var(--text-light);max-width:640px;margin:0 auto}
.blog-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:32px;margin-top:2.5rem}
.blog-card{background:#fff;border-radius:18px;overflow:hidden;box-shadow:0 8px 32px rgba(13,51,17,.06);border:1px solid rgba(27,94,32,.05);transition:transform .3s,box-shadow .3s;display:flex;flex-direction:column}
.blog-card:hover{transform:translateY(-6px);box-shadow:0 20px 48px rgba(13,51,17,.12)}
.blog-card-thumb{aspect-ratio:16/10;display:flex;align-items:center;justify-content:center;color:#fff;font-family:'Noto Serif JP',serif;font-weight:900;letter-spacing:.1em;position:relative;overflow:hidden}
.blog-card-thumb::before{content:'';position:absolute;inset:0;background:radial-gradient(circle at top right,rgba(255,255,255,.2),transparent 60%)}
.blog-thumb-label{font-size:1.6rem;position:relative;z-index:1;text-shadow:0 4px 16px rgba(0,0,0,.25);padding:0 1.5rem;text-align:center}
.blog-card-body{padding:28px 26px 30px;flex:1;display:flex;flex-direction:column}
.blog-card-meta{display:flex;align-items:center;gap:14px;margin-bottom:14px;flex-wrap:wrap}
.blog-category{font-size:.72rem;font-weight:700;padding:4px 12px;border-radius:20px;letter-spacing:.05em}
.blog-date{font-size:.78rem;color:var(--text-light);font-weight:500}
.blog-card-title{font-family:'Noto Serif JP',serif;font-size:1.18rem;font-weight:700;line-height:1.55;color:var(--primary-dark);margin-bottom:14px}
.blog-card-excerpt{font-size:.92rem;line-height:1.85;color:var(--text-light);flex:1;margin-bottom:1.2rem}
.blog-card-readmore{font-size:.88rem;font-weight:700;color:var(--primary);align-self:flex-start;letter-spacing:.05em;border-bottom:2px solid transparent;transition:border-color .2s}
.blog-card:hover .blog-card-readmore{border-bottom-color:var(--accent)}
.back-to-home{text-align:center;margin-top:4rem}
.back-to-home a{display:inline-block;background:linear-gradient(135deg,var(--primary),var(--primary-dark));color:#fff;padding:14px 32px;border-radius:60px;font-weight:600;font-size:.95rem;box-shadow:0 4px 16px rgba(13,51,17,.18);transition:transform .2s,box-shadow .2s}
.back-to-home a:hover{transform:translateY(-2px);box-shadow:0 6px 24px rgba(13,51,17,.28)}
"""


def render_index_page(posts):
    """ブログインデックスページHTML生成"""
    hero_b64 = read_b64("blog-hero") or read_b64("hero")
    hero_img = f'data:image/jpeg;base64,{hero_b64}' if hero_b64 else ""
    cards = []
    for p in posts:
        fm = p["fm"]
        # 抜粋: 最初のpブロックの本文を取得（HTMLタグ除去）
        excerpt = ""
        for b in p["blocks"]:
            if b["type"] == "p":
                excerpt = re.sub(r'<[^>]+>', '', b["text"])
                if len(excerpt) > 110:
                    excerpt = excerpt[:110] + "..."
                break
        cat_color = fm.get("category_color", "#1B5E20")
        slug = fm.get("slug", "")
        cards.append(f"""
        <a href="./{slug}/index.html" class="blog-card">
          <div class="blog-card-thumb" style="background:linear-gradient(135deg,{cat_color},{cat_color}cc)">
            <span class="blog-thumb-label">{fm.get("hero_label", fm.get("category",""))}</span>
          </div>
          <div class="blog-card-body">
            <div class="blog-card-meta">
              <span class="blog-category" style="background:{cat_color}15;color:{cat_color};border:1px solid {cat_color}33">{fm.get("category","")}</span>
              <span class="blog-date">{fm.get("date","")}</span>
            </div>
            <h3 class="blog-card-title">{fm.get("title","")}</h3>
            <p class="blog-card-excerpt">{excerpt}</p>
            <span class="blog-card-readmore">続きを読む &#10132;</span>
          </div>
        </a>""")
    cards_html = "\n".join(cards) if cards else '<p style="text-align:center;color:var(--text-light)">記事を準備中です。</p>'
    css = (common_css() + INDEX_PAGE_CSS).replace("HERO_OVERLAY", V["hero_overlay"])
    page = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ブログ｜{SCHOOL_NAME} 中野校</title>
<meta name="description" content="個別指導塾Kゼミ中野校のブログ。お知らせ・学習コラム・受験対策情報をお届けします。">
<meta property="og:title" content="ブログ｜{SCHOOL_NAME} 中野校">
<meta property="og:type" content="website">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Klee+One:wght@400;600&family=Noto+Sans+JP:wght@400;500;700;900&family=Noto+Serif+JP:wght@500;700;900&display=swap" rel="stylesheet">
<style>{css}</style>
</head>
<body>
<div class="scroll-progress" id="scrollProgress"></div>
{header_html(blog_active=True, depth=0)}
<section class="blog-hero">
  <div class="blog-hero-bg"><img src="{hero_img}" alt="Kゼミの学習風景"></div>
  <div class="blog-hero-overlay"></div>
  <div class="blog-hero-content">
    <div class="blog-hero-label">NEWS &amp; BLOG</div>
    <h1>お知らせ・ブログ</h1>
    <p>Kゼミ中野校からのお知らせ・受験情報・学習コラムをお届けします。中野で30年、子どもたちの学びに寄り添ってきた塾長と講師陣の視点から、保護者と生徒に役立つ情報を発信していきます。</p>
    <div class="breadcrumb">
      <a href="../index.html">ホーム</a>　&gt;　お知らせ・ブログ
    </div>
  </div>
</section>
<section class="blog-section">
  <div class="watermark">BLOG</div>
  <div class="blog-container">
    <div class="blog-section-head">
      <div class="blog-section-label">LATEST POSTS</div>
      <h2 class="blog-section-title">最新の記事</h2>
      <p class="blog-section-desc">受験対策・指導現場のリアル・保護者向けの学習コラムを順次更新中です。</p>
    </div>
    <div class="blog-grid">
{cards_html}
    </div>
    <div class="back-to-home">
      <a href="../index.html">&#10132; ホームに戻る</a>
    </div>
  </div>
</section>
{footer_html()}
{floating_cta(depth=0)}
</body>
</html>"""
    return page


# ============================================================
# Main
# ============================================================
def main():
    md_files = sorted(glob.glob(os.path.join(POSTS_DIR, "*.md")))
    md_files = [f for f in md_files if not os.path.basename(f).startswith("_")]
    if not md_files:
        print("posts/ にMarkdownファイルが見つかりませんでした。")
        return

    posts = []
    for path in md_files:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        fm, body = parse_frontmatter(text)
        blocks = parse_blocks(body)
        posts.append({"fm": fm, "blocks": blocks, "path": path})

    # 日付順（新しい順）にソート
    def parse_date(d):
        try:
            d = d.replace("年", "-").replace("月", "-").replace("日", "")
            return datetime.datetime.strptime(d, "%Y-%m-%d")
        except Exception:
            return datetime.datetime.min
    posts.sort(key=lambda p: parse_date(p["fm"].get("date", "")), reverse=True)

    # 記事個別ページ
    for i, p in enumerate(posts):
        slug = p["fm"].get("slug")
        if not slug:
            print(f"  ! slug 未指定: {p['path']} (スキップ)")
            continue
        related = [q for j, q in enumerate(posts) if j != i]
        out_dir = os.path.join(DIST_DIR, "blog", slug)
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "index.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(render_post_page(p, related))
        size = os.path.getsize(out_path) // 1024
        print(f"  ✓ blog/{slug}/index.html ({size}KB)")

    # ブログインデックス
    blog_index = os.path.join(DIST_DIR, "blog", "index.html")
    os.makedirs(os.path.dirname(blog_index), exist_ok=True)
    with open(blog_index, "w", encoding="utf-8") as f:
        f.write(render_index_page(posts))
    print(f"  ✓ blog/index.html (記事 {len(posts)} 件)")
    print("\n完了。次はデプロイ用に dist/blog/ を deploy-edushift-samples/ にコピーしてください。")


if __name__ == "__main__":
    main()
