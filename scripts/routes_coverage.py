"""
Google Routes API regional coverage data.

Sources:
  - TRANSIT: https://developers.google.com/maps/documentation/routes/coverage
    "Routes API supports all Google Transit partners, EXCLUDING partners in
    Japan and Indian Railway Catering and Tourism Corporation (IRCTC)."
    Coverage is city-level (depends on GTFS partner availability), not country-level.

  - TWO_WHEELER: https://developers.google.com/maps/documentation/routes/coverage-two-wheeled
    Official supported countries list (as of 2025-12-08).

  - BICYCLE: No official exclusion list. Empirically unavailable in most of
    Southeast Asia (Vietnam, Thailand, Malaysia, Indonesia, Philippines, etc.)
    but available in East Asia, Europe, Americas, Oceania.

  - DRIVE / WALK: Generally available worldwide. Some regions (e.g. South Korea)
    may have restrictions due to local mapping regulations.

Empirical verification date: 2026-04-04
"""

# Countries where TRANSIT is officially excluded by Google.
# All other countries with GTFS partners are supported (city-level coverage varies).
TRANSIT_EXCLUDED = {"JP"}  # Japan. Also IRCTC (India long-distance rail) excluded but local transit works.

# Countries where TWO_WHEELER is officially supported.
# Source: https://developers.google.com/maps/documentation/routes/coverage-two-wheeled
TWO_WHEELER_SUPPORTED = {
    "AR",  # Argentina
    "BD",  # Bangladesh
    "BJ",  # Benin
    "BO",  # Bolivia
    "BR",  # Brazil
    "KH",  # Cambodia
    "CL",  # Chile
    "CO",  # Colombia
    "CR",  # Costa Rica
    "DZ",  # Algeria
    "EC",  # Ecuador
    "EG",  # Egypt
    "GH",  # Ghana
    "GT",  # Guatemala
    "HN",  # Honduras
    "HK",  # Hong Kong
    "IN",  # India
    "ID",  # Indonesia
    "KE",  # Kenya
    "LA",  # Laos
    "MY",  # Malaysia
    "MX",  # Mexico
    "MM",  # Myanmar
    "NI",  # Nicaragua
    "NG",  # Nigeria
    "PK",  # Pakistan
    "PY",  # Paraguay
    "PE",  # Peru
    "PH",  # Philippines
    "RW",  # Rwanda
    "SG",  # Singapore
    "ZA",  # South Africa
    "LK",  # Sri Lanka
    "TW",  # Taiwan
    "TH",  # Thailand
    "TG",  # Togo
    "TN",  # Tunisia
    "UG",  # Uganda
    "UY",  # Uruguay
    "VN",  # Vietnam
}

# Countries where BICYCLE is empirically unavailable (no official list).
# These countries typically have TWO_WHEELER instead.
BICYCLE_UNAVAILABLE = {
    "VN",  # Vietnam
    "TH",  # Thailand
    "MY",  # Malaysia
    "ID",  # Indonesia
    "PH",  # Philippines
    "KH",  # Cambodia
    "MM",  # Myanmar
    "LA",  # Laos
    "IN",  # India
    "HK",  # Hong Kong
}


def get_supported_modes(country_code):
    """Return set of supported Routes API modes for a country.

    Args:
        country_code: ISO 3166-1 alpha-2 code (e.g. "JP", "TW", "VN")

    Returns:
        dict with mode names as keys and True/False as values, plus an
        "unsupported" list of mode names not available in this country.
    """
    cc = country_code.upper()

    modes = {
        "driving": True,    # near-universal
        "walking": True,    # near-universal
        "transit": cc not in TRANSIT_EXCLUDED,
        "bicycling": cc not in BICYCLE_UNAVAILABLE,
        "two_wheeler": cc in TWO_WHEELER_SUPPORTED,
    }

    unsupported = [m for m, ok in modes.items() if not ok]

    return {
        "modes": modes,
        "unsupported": unsupported,
        "country_code": cc,
    }


# Quick reference for common trip destinations
COVERAGE_SUMMARY = {
    "JP": {"driving": True, "walking": True, "bicycling": True, "two_wheeler": False, "transit": False},
    "TW": {"driving": True, "walking": True, "bicycling": True, "two_wheeler": True, "transit": True},
    "VN": {"driving": True, "walking": True, "bicycling": False, "two_wheeler": True, "transit": True},
    "TH": {"driving": True, "walking": True, "bicycling": False, "two_wheeler": True, "transit": True},
    "KR": {"driving": True, "walking": True, "bicycling": True, "two_wheeler": False, "transit": True},
    "SG": {"driving": True, "walking": True, "bicycling": True, "two_wheeler": True, "transit": True},
    "US": {"driving": True, "walking": True, "bicycling": True, "two_wheeler": False, "transit": True},
    "GB": {"driving": True, "walking": True, "bicycling": True, "two_wheeler": False, "transit": True},
    "FR": {"driving": True, "walking": True, "bicycling": True, "two_wheeler": False, "transit": True},
    "DE": {"driving": True, "walking": True, "bicycling": True, "two_wheeler": False, "transit": True},
    "AU": {"driving": True, "walking": True, "bicycling": True, "two_wheeler": False, "transit": True},
}
