import re
from typing import Optional


class TickerResolver:
    _alias_map = {
        "tcs": "TCS.NS",
        "tata consultancy services": "TCS.NS",
        "reliance": "RELIANCE.NS",
        "reliance industries": "RELIANCE.NS",
        "infosys": "INFY.NS",
        "infy": "INFY.NS",
        "hdfc bank": "HDFCBANK.NS",
        "icici bank": "ICICIBANK.NS",
        "state bank of india": "SBIN.NS",
        "sbi": "SBIN.NS",
        "itc": "ITC.NS",
        "bharti airtel": "BHARTIARTL.NS",
        "airtel": "BHARTIARTL.NS",
        "larsen and toubro": "LT.NS",
        "l&t": "LT.NS",
        "lt": "LT.NS",
        "axis bank": "AXISBANK.NS",
        "maruti": "MARUTI.NS",
        "sun pharma": "SUNPHARMA.NS",
        "asian paints": "ASIANPAINT.NS",
        "titan": "TITAN.NS",
        "kotak bank": "KOTAKBANK.NS",
        "kotak mahindra bank": "KOTAKBANK.NS",
        "wipro": "WIPRO.NS",
        "ultratech": "ULTRACEMCO.NS",
        "bajaj finance": "BAJFINANCE.NS",
        "adani enterprises": "ADANIENT.NS",
    }
    _stopwords = {"AI", "TOP", "WHY", "BUY", "SELL", "NOW", "INDIA"}

    def resolve(self, query: str, explicit_ticker: Optional[str] = None) -> Optional[str]:
        if explicit_ticker:
            return self.normalize(explicit_ticker)

        lowered = re.sub(r"[^a-z0-9&.\s-]", " ", query.lower())
        for alias, symbol in sorted(self._alias_map.items(), key=lambda item: len(item[0]), reverse=True):
            if alias in lowered:
                return symbol

        for token in re.findall(r"\b[A-Z][A-Z0-9.&-]{1,11}\b", query):
            if token.upper() not in self._stopwords:
                return self.normalize(token)
        return None

    def normalize(self, ticker: str) -> str:
        symbol = ticker.strip().upper()
        if ":" in symbol:
            root, exchange = symbol.split(":", 1)
            if exchange == "NSE":
                return f"{root}.NS"
            if exchange == "BSE":
                return f"{root}.BO"
            return symbol
        if symbol.endswith(".NSE"):
            return f"{symbol[:-4]}.NS"
        if symbol.endswith(".BSE"):
            return f"{symbol[:-4]}.BO"
        if symbol.endswith(".NS") or symbol.endswith(".BO"):
            return symbol
        return f"{symbol}.NS"
