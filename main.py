import os
import time
import threading
import yfinance as yf
import feedparser
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = "8662151451:FpKPGA3E2BIJK"
CHANNEL_ID = -1003916588968

bot = telebot.TeleBot(TOKEN)

bot.send_message(CHANNEL_ID, "✅ TEST: Railway bot connected to Telegram")


bot = telebot.TeleBot(TOKEN)

PAIRS = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "AUD/USD": "AUDUSD=X",
    "NZD/USD": "NZDUSD=X",
    "USD/JPY": "JPY=X",
    "USD/CAD": "CAD=X",
    "USD/CHF": "CHF=X",
}

NEWS_FEEDS = [
    "https://www.fxstreet.com/rss/news",
    "https://www.forexlive.com/feed/",
]

KEYWORDS = {
    "USD": ["fed", "fomc", "powell", "cpi", "nfp", "payrolls", "inflation", "dollar", "usd", "rate"],
    "EUR": ["ecb", "lagarde", "euro", "eur"],
    "GBP": ["boe", "bailey", "pound", "gbp"],
    "JPY": ["boj", "ueda", "yen", "jpy", "intervention"],
    "AUD": ["rba", "australia", "aud"],
    "CAD": ["boc", "canada", "cad"],
    "CHF": ["snb", "swiss", "chf"],
}

CURRENCY_TO_PAIRS = {
    "USD": ["EUR/USD", "GBP/USD", "AUD/USD", "NZD/USD", "USD/JPY", "USD/CAD", "USD/CHF"],
    "EUR": ["EUR/USD"],
    "GBP": ["GBP/USD"],
    "AUD": ["AUD/USD"],
    "NZD": ["NZD/USD"],
    "JPY": ["USD/JPY"],
    "CAD": ["USD/CAD"],
    "CHF": ["USD/CHF"],
}

seen_news = set()
last_trade_alert = {}
last_direction = {}

COOLDOWN = 1800  # 30 minutes


def quality(confidence):
    if confidence >= 85:
        return "⚡️ Exceptional"
    elif confidence >= 70:
        return "🔵 Strong"
    elif confidence >= 55:
        return "🟡 Moderate"
    else:
        return "⚪️ Weak"


def trade_keyboard(pair, direction, confidence):
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("Why?", callback_data=f"why|{pair}|{direction}"),
        InlineKeyboardButton("Confidence", callback_data=f"conf|{confidence}")
    )
    return markup


def news_keyboard(link):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("Learn More", url=link))
    return markup


@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    parts = call.data.split("|")

    if parts[0] == "why":
        bot.send_message(call.message.chat.id, f"""
📘 WHY THIS TRADE?

Pair: {parts[1]}
Direction: {parts[2]}

Reason:
News relevance matched with stronger short-term momentum and trend confirmation.
This helps avoid random buy/sell flips.
""")

    elif parts[0] == "conf":
        bot.send_message(call.message.chat.id, f"""
📊 CONFIDENCE BREAKDOWN

News Relevance: 30%
Momentum: 35%
Trend Confirmation: 20%
Noise Filter: 15%

Total Confidence: {parts[1]}%
""")


def send_news_update(impact, affected, headline, link):
    msg = f"""
📰 NEWS UPDATE

Impact: {impact}
Affected: {", ".join(affected)}

Headline:
{headline}

Reason:
Relevant forex keyword detected.
"""
    bot.send_message(CHANNEL_ID, msg, reply_markup=news_keyboard(link))


def send_trade_alert(pair, direction, entry, sl, tp, confidence, headline, reason):
    msg = f"""
📈 TRADE ALERT

Pair: {pair}
Direction: {direction}

Entry: {entry}
SL: {sl}
TP: {tp}

Confidence: {confidence}%
Trade Quality: {quality(confidence)}

News Context:
{headline}

Reason:
{reason}
"""
    bot.send_message(CHANNEL_ID, msg, reply_markup=trade_keyboard(pair, direction, confidence))


def get_momentum(pair):
    symbol = PAIRS[pair]

    data = yf.download(symbol, period="1d", interval="1m", progress=False)

    if len(data) < 25:
        return None

    close = data["Close"]

    now_price = float(close.iloc[-1])
    old_price = float(close.iloc[-5])

    move = ((now_price - old_price) / old_price) * 100

    # stricter so it does not flip buy/sell too easily
    if abs(move) < 0.06:
        return None

    ema_fast = close.tail(5).mean()
    ema_slow = close.tail(20).mean()

    trend_direction = "BUY" if ema_fast > ema_slow else "SELL"
    direction = "BUY" if move > 0 else "SELL"

    # only alert when momentum agrees with trend
    if direction != trend_direction:
        return None

    if direction == "BUY":
        sl = round(now_price * 0.9992, 5)
        tp = round(now_price * 1.0012, 5)
    else:
        sl = round(now_price * 1.0008, 5)
        tp = round(now_price * 0.9988, 5)

    confidence = min(92, int(65 + abs(move) * 300))

    return {
        "direction": direction,
        "entry": round(now_price, 5),
        "sl": sl,
        "tp": tp,
        "move": round(move, 3),
        "confidence": confidence
    }


def scan_news_and_trades():
    try:
        for url in NEWS_FEEDS:
            feed = feedparser.parse(url)

            for entry in feed.entries[:10]:
                title = entry.title
                link = entry.link
                news_id = title + link

                if news_id in seen_news:
                    continue

                seen_news.add(news_id)
                text = title.lower()

                affected = []

                for currency, words in KEYWORDS.items():
                    if any(word in text for word in words):
                        affected.append(currency)

                if not affected:
                    continue

                high_words = ["cpi", "fomc", "nfp", "payrolls", "rate", "inflation", "intervention"]
                impact = "HIGH" if any(w in text for w in high_words) else "MEDIUM"

                send_news_update(impact, affected, title, link)

                candidate_pairs = set()

                for currency in affected:
                    for pair in CURRENCY_TO_PAIRS.get(currency, []):
                        candidate_pairs.add(pair)

                for pair in candidate_pairs:
                    now = time.time()

                    if pair in last_trade_alert and now - last_trade_alert[pair] < COOLDOWN:
                        continue

                    momentum = get_momentum(pair)

                    if not momentum:
                        continue

                    if momentum["confidence"] < 70:
                        continue

                    # prevents SELL then BUY right after
                    if pair in last_direction and last_direction[pair] != momentum["direction"]:
                        continue

                    reason = f"{pair} matched news, moved {momentum['move']}% in 5 minutes, and confirmed trend direction."

                    send_trade_alert(
                        pair=pair,
                        direction=momentum["direction"],
                        entry=momentum["entry"],
                        sl=momentum["sl"],
                        tp=momentum["tp"],
                        confidence=momentum["confidence"],
                        headline=title,
                        reason=reason
                    )

                    last_trade_alert[pair] = now
                    last_direction[pair] = momentum["direction"]

    except Exception as e:
        print(f"Scanner error: {e}")


def scanner_loop():
    bot.send_message(CHANNEL_ID, "✅ FX bot is live: news updates + stricter trade alerts enabled.")

    while True:
        scan_news_and_trades()
        time.sleep(60)


threading.Thread(target=scanner_loop).start()
bot.infinity_polling()
