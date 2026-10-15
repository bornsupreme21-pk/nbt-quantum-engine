GOVT_KEYWORDS = [
    'cabinet', 'govt', 'government', 'pib', 'ministry', 'rbi', 'sebi', 'pli',
    'subsidy', 'tender', 'psu', 'railway', 'defence', 'defense', 'nhai',
    'ntpc', 'budget', 'gst', 'duty', 'rate cut', 'restructuring', 'disinvestment'
]
BULL_KEYWORDS = [
    'order', 'win', 'bag', 'profit', 'surge', 'jump', 'dividend', 'bonus',
    'split', 'upgrade', 'buy', 'approval', 'acquire', 'expansion', 'record',
    'mou', 'partner', 'launch'
]
BEAR_KEYWORDS = [
    'loss', 'fall', 'drop', 'penalty', 'raid', 'fraud', 'downgrade',
    'default', 'resign', 'pledge', 'ban', 'notice', 'probe', 'fire', 'strike', 'weak'
]

def fetch_stock_news_catalyst(symbol, company, current_tag):
    """Harvests overnight (8 AM), opening (9:30 AM), and Govt/Policy (1 PM) headlines."""
    try:
        query = urllib.parse.quote(f"{company} {symbol} NSE stock")
        url = f"https://news.google.com/rss/search?q={query}+when:2d&hl=en-IN&gl=IN&ceid=IN:en"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=4) as response:
            xml_data = response.read()
        root = ET.fromstring(xml_data)
        item = root.find('.//item')
        if item is not None:
            title = item.find('title').text or ""
            clean_title = title.split(" - ")[0].strip()
            low_t = clean_title.lower()
            if any(k in low_t for k in GOVT_KEYWORDS):
                sentiment = "🏛️ GOVT/POLICY"
            elif any(k in low_t for k in BULL_KEYWORDS):
                sentiment = "🟢 BULL NEWS"
            elif any(k in low_t for k in BEAR_KEYWORDS):
                sentiment = "🔴 RISK NEWS"
            else:
                sentiment = "📰 NEWS"
            short_headline = clean_title[:52] + ("..." if len(clean_title) > 52 else "")
            if current_tag == "⚪ Normal Flow":
                return f"{sentiment}: {short_headline}"
            return f"{current_tag} | {sentiment}: {short_headline}"
    except Exception:
        pass
    return current_tag
