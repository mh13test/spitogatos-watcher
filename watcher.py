import asyncio
import re
import os
from playwright.async_api import async_playwright
import requests

SEARCH_URL = "https://www.spitogatos.gr/en/for_sale-houses/corinthia?maximum_price=150000"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

MIN_PLOT = 100
CHECK_INTERVAL = 900  # 15 minutes

seen = set()

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text})

async def check():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(SEARCH_URL)
        await page.wait_for_timeout(5000)

        links = await page.eval_on_selector_all(
            "a", "elements => elements.map(e => e.href)"
        )

        property_links = [
            l for l in links
            if l and "spitogatos" in l and ("for_sale" in l or "property" in l)
        ]

        for link in property_links[:20]:
            if link in seen:
                continue

            seen.add(link)

            await page.goto(link)
            await page.wait_for_timeout(3000)

            content = await page.content()

            plot_match = re.search(r"(\d{3,5})\s*(m2|m²|sqm|stremma)", content.lower())
            price_match = re.search(r"€\s*([\d\.,]+)", content)

            if not plot_match or not price_match:
                continue

            plot_value = float(plot_match.group(1).replace(",", "."))

            if "strem" in plot_match.group(2):
                plot_value *= 1000

            if plot_value >= MIN_PLOT:
                price = price_match.group(1)

                send_telegram(
                    f"🏡 Nouvelle annonce\n\n"
                    f"💰 {price} €\n"
                    f"🌿 Plot: {int(plot_value)} m²\n"
                    f"🔗 {link}"
                )

        await browser.close()

async def main():
    send_telegram("✅ Watcher démarré (Corinthia ≤150k, plot ≥1000m²)")
    while True:
        try:
            await check()
        except Exception as e:
            print("Error:", e, flush=True)
        await asyncio.sleep(CHECK_INTERVAL)

asyncio.run(main())

