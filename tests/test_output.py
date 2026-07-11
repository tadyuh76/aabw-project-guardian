from social_crawler.output import partial_output_path


def test_partial_output_path_preserves_stdout() -> None:
    assert partial_output_path("data/mentions.json") == "data/mentions.json.partial"
    assert partial_output_path("-") == "-"
