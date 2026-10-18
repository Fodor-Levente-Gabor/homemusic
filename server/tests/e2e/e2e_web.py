"""Böngészős végpontok közötti teszt (Playwright). Előfeltétel: python tests/devserver.py fut a 8099-es porton."""
import json
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8099"
SHOTS = sys.argv[1] if len(sys.argv) > 1 else "/tmp"


def api(path, token, method="GET", body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req).read() or b"{}")


def start(ctx):
    p = ctx.new_page()
    errors = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    p.goto(BASE)
    p.fill("input[type=password]", "titok")
    p.click("text=Belépés")
    p.click("text=Lejátszó indítása")
    p.wait_for_selector(".bar")
    return p, errors


with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
    ctx1 = b.new_context(viewport={"width": 1400, "height": 850})
    p1, err1 = start(ctx1)
    token = p1.evaluate("localStorage.getItem('hm_token')")
    p1.wait_for_selector(".shelf .card")
    p1.screenshot(path=f"{SHOTS}/1_home.png")

    # --- keresés és lejátszás ---
    p1.fill(".search input", "teszt")
    p1.press(".search input", "Enter")
    p1.wait_for_selector(".row")
    p1.screenshot(path=f"{SHOTS}/2_search.png")
    p1.click(".row .cv")
    p1.wait_for_function("document.querySelector('.bar .now .ellip').textContent.includes('teszt 1')", timeout=30000)
    t0 = p1.evaluate("document.querySelector('.bar .ctrl span').textContent")
    time.sleep(2)
    t1 = p1.evaluate("document.querySelector('.bar .ctrl span').textContent")
    assert t0 != t1, f"a pozíció nem halad: {t0} {t1}"
    print("lejátszás OK", t0, "->", t1)

    # --- automatikus továbblépés (gapless, 12 mp-es számok) ---
    p1.wait_for_function("!document.querySelector('.bar .now .ellip').textContent.includes('teszt 1')", timeout=30000)
    print("következő szám automatikusan OK")
    lyr_urls = []
    p1.on("request", lambda r: lyr_urls.append(r.url) if "/lyrics/" in r.url and r.method == "PATCH" else None)

    # --- lyrics: beillesztés + kézi sync ---
    vid = p1.evaluate("(() => { return null })()")
    p1.click(".bar .right button[title=Szöveg]")
    p1.wait_for_selector("textarea")
    p1.fill("textarea", "első sor\nmásodik sor\nharmadik sor")
    p1.click("text=Mentés")
    p1.wait_for_selector(".lyr p")
    p1.click("text=Sync")
    assert "kezdődik" in p1.inner_text(".syncbar .next")
    for i in range(3):
        time.sleep(0.7)
        p1.keyboard.press("Space")
        if i == 0:      # az 1. sor időzítése után az 1. sor a "most éneklett" (kiemelt), a 2. a következő
            assert p1.inner_text(".lyr p.act") == "első sor" and p1.inner_text(".lyr p.syncnext") == "második sor"
    p1.wait_for_selector("text=szinkronizált", timeout=5000)
    p1.screenshot(path=f"{SHOTS}/3_lyrics.png")
    p1.wait_for_timeout(300)
    vid = lyr_urls[0].split("/lyrics/")[1].split("/")[0]
    ly = api(f"/api/lyrics/{vid}", token)
    assert [l["text"] for l in ly["lines"]][0] == "első sor"
    assert ly["synced"] and [l["t"] for l in ly["lines"]] == sorted(l["t"] for l in ly["lines"]), ly
    print("lyrics sync OK", [l["t"] for l in ly["lines"]])
    p1.click(".np .tabs button[title=Bezárás]")

    # --- remote control: második eszköz ---
    ctx2 = b.new_context(viewport={"width": 1200, "height": 800})
    p2, err2 = start(ctx2)
    p2.wait_for_function("document.querySelector('.pill').textContent.includes('2 eszköz')", timeout=10000)
    p2.click(".bar .right button[title^=Eszközök]")
    p2.click("text=Távirányító")
    p2.wait_for_function("document.querySelector('.remote-tag')", timeout=5000)
    p2.screenshot(path=f"{SHOTS}/4_remote.png")
    # a 2. eszközről megállítjuk az 1.-et
    p1.wait_for_function("document.querySelector('.bar .ctrl .big svg path').getAttribute('d').startsWith('M6 19')", timeout=5000)  # pause ikon = szól
    p2.click(".bar .ctrl .big")
    p1.wait_for_function("document.querySelector('.bar .ctrl .big svg path').getAttribute('d').startsWith('M8 5')", timeout=5000)   # play ikon = megállt
    print("remote pause OK")
    p2.click(".bar .ctrl .big")
    p1.wait_for_function("document.querySelector('.bar .ctrl .big svg path').getAttribute('d').startsWith('M6 19')", timeout=5000)
    print("remote play OK")
    # és fordítva: az 1. eszköz irányítja a 2.-at (átvitel)
    p1.click(".bar .right button[title^=Eszközök]")
    p1.click("text=Lejátszás átvitele oda")
    p2.click(".bar .now")  # nem fontos
    print("átvitel elküldve")

    print("konzol hibák 1:", [e for e in err1 if "favicon" not in e][:5])
    print("konzol hibák 2:", [e for e in err2 if "favicon" not in e][:5])
    b.close()
