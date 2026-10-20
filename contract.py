"""Data contract for the AI Corporations dashboard: the single source of truth.

validate_data.py checks every CSV against this file and app/data_loader.py reads it.
Change it only after talking to Reid, because everyone's files depend on it.

Column spec: (name, kind, required). Kinds: str, url, date, float, pos_float, int,
nonneg_int, period, source_id, or ("enum", [allowed values]).
"""

COMPANIES = ["Google", "OpenAI", "Anthropic", "Nvidia", "Apple"]  # Alphabet -> "Google"
TICKERS = ["GOOGL", "NVDA", "AAPL"]

TIER1_DOC_TYPES = [
    "10-K", "10-Q", "8-K", "earnings_release", "press_release",
    "pricing_page", "docs", "newsroom", "blog",
]
TIER2_DOC_TYPES = ["news", "interview", "report", "market_data"]
DOC_TYPES = TIER1_DOC_TYPES + TIER2_DOC_TYPES
NEWS_ONLY_TIER2 = ["news", "market_data"]  # these doc types can never be tier 1

RELATIONSHIPS = ["investment", "supply", "cloud", "distribution", "competition", "financing"]  # financing: guarantees, loans, warrants
CONFIDENCE = ["high", "medium", "low"]
EVENT_TYPES = ["earnings", "price_change", "promo_end", "deprecation"]
EVENT_STATUS = ["confirmed", "reported"]  # confirmed = announced by the company itself (tier 1); reported = press only (tier 2)
UNITS = ["USD_millions", "percent", "USD_per_share", "count"]
BOUNDS = ["approximately", "at_least"]  # how a private company worded its figure: "about $9B" vs "surpassed $30B"

# Use these metric names where they apply so charts line up. Others are allowed
# (snake_case) but produce a warning.
RECOMMENDED_METRICS = [
    "revenue", "net_income", "operating_income", "capex", "eps_diluted",
    "cloud_revenue", "data_center_revenue", "services_revenue", "gross_margin_pct",
]

SOURCES_SCHEMA = [
    ("source_id", "source_id", True),   # A-001, B-014, R-003 (prefix = owner file)
    ("company", ("enum", COMPANIES), True),
    ("title", "str", True),
    ("url", "url", True),
    ("publisher", "str", True),
    ("doc_type", ("enum", DOC_TYPES), True),
    ("tier", ("enum", ["1", "2"]), True),
    ("published_date", "date", True),
    ("retrieved_date", "date", True),
    ("local_path", "str", False),       # relative to data/, e.g. raw/Nvidia/A-001.pdf
]

SCHEMAS = {
    "financials.csv": [
        ("company", ("enum", COMPANIES), True),
        ("period", "period", True),         # company's own fiscal label, e.g. FY2027Q1
        ("period_end", "date", True),       # calendar date the period ended (for alignment)
        ("metric", "str", True),
        ("value", "float", True),
        ("unit", ("enum", UNITS), True),
        ("source_id", "source_id", True),
        ("as_of", "date", True),            # date the value was fetched
    ],
    "stock_prices.csv": [
        ("date", "date", True),
        ("ticker", ("enum", TICKERS), True),
        ("close", "pos_float", True),
        ("volume", "nonneg_int", True),
    ],
    "token_pricing.csv": [
        ("company", ("enum", COMPANIES), True),
        ("model", "str", True),
        ("input_usd_per_1m", "pos_float", True),
        ("output_usd_per_1m", "pos_float", True),
        ("cached_input_usd_per_1m", "pos_float", False),
        ("context_window", "nonneg_int", False),
        ("source_id", "source_id", True),
        ("captured_date", "date", True),
    ],
    "partnerships.csv": [
        ("from_company", "str", True),      # any entity (e.g. Microsoft, TSMC)...
        ("to_company", "str", True),        # ...but at least one end must be in COMPANIES
        ("relationship_type", ("enum", RELATIONSHIPS), True),
        ("description", "str", True),
        ("amount_usd", "pos_float", False),
        ("date", "date", True),
        ("source_id", "source_id", True),
        ("confidence", ("enum", CONFIDENCE), True),
    ],
    "events.csv": [                          # dated, sourced things we know are coming
        ("company", ("enum", COMPANIES), True),
        ("event_type", ("enum", EVENT_TYPES), True),
        ("event_date", "date", True),
        ("description", "str", True),
        ("source_id", "source_id", True),
        ("status", ("enum", EVENT_STATUS), True),
    ],
    "guidance.csv": [                        # numbers a company itself said to expect (never our forecasts)
        ("company", ("enum", COMPANIES), True),
        ("metric", "str", True),
        ("target_period", "period", True),   # the quarter the guidance is about, e.g. FY2027Q3
        ("value", "float", True),            # midpoint as stated
        ("tolerance_pct", "float", False),   # "plus or minus 2%" -> 2
        ("unit", ("enum", UNITS), True),
        ("source_id", "source_id", True),
        ("issued_date", "date", True),
    ],
    "private_revenue.csv": [                 # figures private companies state themselves (no SEC filings, no quarters)
        ("company", ("enum", COMPANIES), True),
        ("metric", "str", True),             # run_rate_revenue = current revenue annualized, NOT a quarter's revenue
        ("as_of", "date", True),             # the date the figure describes ("end of 2025" -> 2025-12-31)
        ("value", "float", True),            # as stated, e.g. 30000 for "surpassed $30 billion"
        ("unit", ("enum", UNITS), True),
        ("bound", ("enum", BOUNDS), True),
        ("quote", "str", True),              # the company's exact words; the verifier finds them in the document
        ("source_id", "source_id", True),
    ],
}

# Unique keys per table (duplicates are errors)
UNIQUE_KEYS = {
    "financials.csv": ["company", "period", "metric"],
    "stock_prices.csv": ["date", "ticker"],
    "token_pricing.csv": ["company", "model", "captured_date"],
    "events.csv": ["company", "event_type", "event_date", "description"],
    "guidance.csv": ["company", "metric", "target_period", "issued_date"],
    "private_revenue.csv": ["company", "metric", "as_of"],
}
