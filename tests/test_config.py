from social_crawler.config import resolve_platform_domains


def test_resolve_platform_domains_splits_timed_and_untimed() -> None:
    timed, untimed = resolve_platform_domains(["twitter", "telegram", "zalo"])

    assert timed == ["x.com", "twitter.com"]
    assert "t.me" in untimed
    assert "zalo.me" in untimed
    assert "facebook.com" not in timed
