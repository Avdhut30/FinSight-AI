from app.services.ticker_resolver import TickerResolver


def test_resolves_known_company_names():
    resolver = TickerResolver()
    assert resolver.resolve("Should I buy Infosys now?") == "INFY.NS"
    assert resolver.resolve("Why did Reliance fall today?") == "RELIANCE.NS"


def test_normalizes_explicit_ticker():
    resolver = TickerResolver()
    assert resolver.resolve("Analyze TCS", explicit_ticker="tcs") == "TCS.NS"
    assert resolver.resolve("Analyze TCS", explicit_ticker="tcs:nse") == "TCS.NS"
    assert resolver.resolve("Analyze TCS", explicit_ticker="tcs.nse") == "TCS.NS"
