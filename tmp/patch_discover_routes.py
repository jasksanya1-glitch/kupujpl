"""Minimal prod patches: SEO allowlist for redakcja/feed + /feed.xml alias."""
from pathlib import Path

st = Path("/opt/kupujpl-games/app/core/site_tracking.py")
text = st.read_text(encoding="utf-8")
old = """    if path.startswith("/sitemap") or path == "/robots.txt":
        return True
    if path.startswith("/og/"):
        return True
    return False"""
new = """    if path.startswith("/sitemap") or path == "/robots.txt":
        return True
    if path in {"/redakcja", "/feed.xml", "/o-nas", "/kontakt", "/wsparcie"}:
        return True
    if path.startswith("/og/"):
        return True
    return False"""
if old not in text:
    raise SystemExit("site_tracking pattern not found")
st.write_text(text.replace(old, new, 1), encoding="utf-8")
print("site_tracking patched")

main = Path("/opt/kupujpl-games/app/main.py")
mt = main.read_text(encoding="utf-8")
needle = """@app.get("/blog/feed.xml", response_class=Response)
def blog_feed(db: Session = Depends(get_db)):
    return Response(content=blog_rss_xml(db), media_type="application/rss+xml; charset=utf-8")"""
alias = """@app.get("/feed.xml", response_class=Response)
@app.get("/blog/feed.xml", response_class=Response)
def blog_feed(db: Session = Depends(get_db)):
    return Response(content=blog_rss_xml(db), media_type="application/rss+xml; charset=utf-8")"""
if '@app.get("/feed.xml"' in mt:
    print("feed alias already present")
elif needle not in mt:
    raise SystemExit("main feed pattern not found")
else:
    main.write_text(mt.replace(needle, alias, 1), encoding="utf-8")
    print("main feed alias added")
