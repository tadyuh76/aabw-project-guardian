import json

from social_crawler.cli import main


def test_plan_runs_without_api_key(capsys) -> None:
    exit_code = main(["plan", "--keyword", "Example Brand", "--platform", "facebook"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert len(payload["requests"]) == 1
    assert payload["requests"][0]["query"] == '"example brand" (site:facebook.com)'
