import os
import time
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SEARCH_URL = os.getenv("SEARCH_URL")

MAX_PRICE = int(os.getenv("MAX_PRICE_EUR", "150000"))
MIN_PLOT = int(os.getenv("MIN_PLOT_M2", "1000"))
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "900"))

seen = set()

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message}
    requests.post(url, data=data)

def extract_plot(text):
    import re
    text = text.lower()

    # stremma (1 = 1000m2)
    stremma = re.search(r"(\d+(?:[.,]\d+)?)\s*(stremma|στρεμ|στρ)", text)
    if stremma:
        return int(float(stremma.group(1).replace(",", ".")) * 1000)

    # m2
    m2 = re.search(r"(\d{3,5})\s*(m2|sqm|m²)", text)
    if m2:
        return int(m2.group(1))

    return None

def check_listings():
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(SEARCH_URL, headers=headers)
    soup = BeautifulSoup(r.text, "lxml")

    for a in soup.find_all("a", href=True):
        link = a["href"]
        if "property" not in link:
            continue

        full_link = "https://www.spitogatos.gr" + link

        if full_link in seen:
            continue

        seen.add(full_link)

        page = requests.get(full_link, headers=headers)
        text = page.text.lower()

        # price
        import re
        price_match = re.search(r"(\d{4,7})\s*€", text)
        if not price_match:
            continue

        price = int(price_match.group(1))
        if price > MAX_PRICE:
            continue

        plot = extract_plot(text)
        if plot and plot >= MIN_PLOT:
            send_telegram(
                f"🏡 NEW MATCH\n\n💰 {price}€\n🌿 Plot: {plot}m2\n🔗 {full_link}"
            )

print("Watcher started...")

while True:
    try:
        check_listings()
    except Exception as e:
        print("Error:", e)

    time.sleep(POLL_SECONDS)
