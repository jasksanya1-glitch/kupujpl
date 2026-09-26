"""Placeholder for future Google Search Console API integration.

Discover performance is evaluated in GSC UI — there is no API to "enable Discover".
This module only documents hooks for later reporting exports.
"""
from __future__ import annotations

from typing import Any


def search_console_integration_status() -> dict[str, Any]:
    return {
        "configured": False,
        "note": (
            "Google Discover cannot be enabled via API. "
            "After deploy, submit sitemaps in Search Console and monitor Discover/News reports."
        ),
        "recommended_property": "https://kupujpl.pl/games/",
        "sitemaps": [
            "https://kupujpl.pl/games/sitemap.xml",
            "https://kupujpl.pl/games/sitemap-blog.xml",
            "https://kupujpl.pl/games/sitemap-news.xml",
        ],
    }
