import logging

from social_crawler.serpapi import (
    filter_organic_results_by_domains,
    has_valid_organic_results,
)


def test_http_client_request_logging_is_suppressed() -> None:
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING


def test_rejects_spelling_corrected_results() -> None:
    result = {
        "search_information": {"spelling_fix": "different brand"},
        "organic_results": [{"link": "https://facebook.com/example"}],
    }

    assert has_valid_organic_results(result) is False


def test_filters_results_to_allowed_hosts() -> None:
    results = [
        {"link": "https://www.facebook.com/example"},
        {"link": "https://sub.reddit.com/r/example"},
        {"link": "https://example.com/off-domain"},
    ]

    assert filter_organic_results_by_domains(results, ["facebook.com"]) == [results[0]]
