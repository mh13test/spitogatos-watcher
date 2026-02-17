import asyncio
import os
import re
import time
import hashlib
import requests
from playwright.async_api import async_playwright

# Mets ici EXACTEMENT l'URL de ta recherche Spitogatos (copie/colle depuis le navigateur)
# IMPORTANT: idealement la meme que celle de ton alerte sauvegardee (Corinthia + detached + max 150k)
SEARCH_URL = os.getenv(
    "SEARCH_URL",
    "https://www.spitogatos.gr/en/for_sale-houses/corinthia?maximum_price=150000",
)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

MIN_PLOT_M2 = int(os.getenv("MIN_PLOT_M2", "1000"))
MAX_PRICE_EUR = int(os.getenv("MAX_PRICE_EUR", "150000"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "900"))  # 15 min

USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36",
)

def send_telegram(text: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        print("WARN: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID manquant", flush=True)
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": False}, timeout=25)
    if r.status_code != 200:
        print(f"WARN: telegram send failed status={r.status_code} body={r.text[:300]}", flush=True)

def normalize_price_eur(text: str):
    # accepte "€ 95.000" / "95,000 €" / "95000€"
    m = re.search(r"€\s*([\d\.,]+)", text)
    if not m:
        m = re.search(r"([\d\.,]+)\s*€", text)
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(",", "")
    try:
        return int(raw)
    except ValueError:
        return None

def parse_plot_m2(text: str):
    t = " ".join(text.replace("\xa0", " ").split()).lower()

    # stremma (1 = 1000 m²) ex: "1.5 stremma" / "2,3 στρεμ"
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(stremma|stremmata|στρεμμα|στρέμμα|στρεμ|στρ)\b", t)
    if m:
        val = m.group(1).replace(",", ".")
        try:
            return int(float(val) * 1000)
        except ValueError:
            return None

    # m² / sqm ex: "1.200 m²" / "1,200 sqm" / "1200 m2"
    m = re.search(r"(\d{1,3}(?:[.,]\d{3})+|\d+)\s*(m2|m²|sqm|sq\.m|τ\.μ|τμ)\b", t)
    if m:
        raw = m.group(1).replace(".", "").replace(",", "")
        try:
            return int(raw)
        except ValueError:
            return None

    return None

def stable_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

# On garde un cache en memoire (si le container redemarre, il repartira a zero)
seen = set()

async def fetch_listing_links(page) -> list[str]:
    # essaie large: toutes les ancres avec href
    hrefs = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
    hrefs = [h for h in hrefs if h and "spitogatos" in h]
    # garde des liens qui ressemblent a des fiches
    candidates = []
    for h in hrefs:
        if any(k in h for k in ["for_sale", "property", "listing", "aggelia"]):
            candidates.append(h)
    # dedupe
    out = []
    s = set()
    for h in candidates:
        if h not in s:
            s.add(h)
            out.append(h)
    return out

async def run_cycle():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        page = await context.new_page()

        print(f"[INFO] goto search: {SEARCH_URL}", flush=True)
        await page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(4000)

        html = await page.content()
        if "Pardon Our Interruption" in html or "hcaptcha" in html.lower():
            print("[WARN] Bloque par protection anti-bot sur la page de recherche (captcha).", flush=True)
            # On notifie une seule fois par cycle (sans contournement)
            send_telegram("⚠️ Watcher: Spitogatos affiche une page de verification (captcha). Lecture automatique bloquee.")
            await browser.close()
            return

        links = await fetch_listing_links(page)
        print(f"[INFO] links found: {len(links)}", flush=True)

        posted = 0
        checked = 0

        for link in links[:40]:
            if link in seen:
                continue
            seen.add(link)
            checked += 1

            try:
                await page.goto(link, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(2500)

                content = await page.content()
                text = (await page.inner_text("body")).strip()

                if "Pardon Our Interruption" in content or "hcaptcha" in content.lower():
                    print(f"[WARN] bloque (captcha) sur annonce: {link}", flush=True)
                    continue

                price = normalize_price_eur(text) or normalize_price_eur(content)
                plot = parse_plot_m2(text) or parse_plot_m2(content)

                # logs de debug (sans spam telegram)
                print(f"[INFO] listing {stable_id(link)} price={price} plot={plot} url={link}", flush=True)

                # Filtrage budget (securite, meme si tu as deja max 150k sur la recherche)
                if price is not None and price > MAX_PRICE_EUR:
                    continue

                if plot is None or plot < MIN_PLOT_M2:
                    continue

                send_telegram(
                    "🏡 MATCH – Corinthia\n\n"
                    f"💰 {price if price is not None else 'n/a'} €\n"
                    f"🌿 Plot: {plot} m² (min {MIN_PLOT_M2})\n"
                    f"🔗 {link}"
                )
                posted += 1

            except Exception as e:
                print(f"[WARN] listing failed url={link} err={e}", flush=True)

        print(f"[INFO] cycle done checked={checked} posted={posted}", flush=True)
        await browser.close()

async def main():
    print("BOOT: watcher demarre", flush=True)
    send_telegram("✅ Watcher en ligne (Railway) – Corinthia ≤150k – plot ≥1000m²")
    while True:
        try:
            await run_cycle()
        except Exception as e:
            print(f"[WARN] cycle failed err={e}", flush=True)
        await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
