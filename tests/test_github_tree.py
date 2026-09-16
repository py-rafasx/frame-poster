from src.github_tree import _parse_repo


def test_parse_repo_owner_repo_branch():
    assert _parse_repo("py-rafasx/season2/master") == (
        "py-rafasx",
        "season2",
        "master",
        "",
    )


def test_parse_repo_with_path_prefix():
    assert _parse_repo("py-rafasx/season2/master/01/") == (
        "py-rafasx",
        "season2",
        "master",
        "01",
    )


def test_parse_repo_nested_prefix():
    assert _parse_repo("user/repo/branch/01/sub/") == (
        "user",
        "repo",
        "branch",
        "01/sub",
    )
