from pathlib import Path

from jupiter_data_transform.main import build_parser, load_mints


def test_cli_names_schema_initialization_explicitly() -> None:
    args = build_parser().parse_args(["init-schema"])
    assert args.command == "init-schema"


def test_load_mints_removes_blanks_comments_and_duplicates(tmp_path: Path) -> None:
    mints_file = tmp_path / "mints.txt"
    mints_file.write_text("# comment\nmint-b\n\nmint-a\n", encoding="utf-8")

    assert load_mints(["mint-a"], mints_file) == ["mint-a", "mint-b"]
