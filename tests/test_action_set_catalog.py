"""Catalog descriptions for action sets with no hand-written description.

The agent chooses which sets to load from this catalog. When every
integration sub-set read "Custom action set: <name>" the agent loaded only
the shortlist set and fell back to raw SQL for bucket/secret management
(seen live testing Supabase, 2026-10-05). These tests pin the contract:
the shortlist says it is a shortlist, and sub-sets name what is inside.
"""

from app.action.action_set import describe_set

SETS = {
    "supabase": ["list_supabase_projects", "run_supabase_sql", "delete_supabase_files"],
    "supabase_storage": [
        "list_supabase_buckets",
        "create_supabase_bucket",
        "delete_supabase_bucket",
        "upload_supabase_file",
        "list_supabase_files",
        "create_supabase_signed_url",
    ],
    "supabase_secrets": ["list_supabase_secrets", "set_supabase_secrets"],
    "supabase_branches": ["list_supabase_branches", "merge_supabase_branch"],
    "google_drive": ["list_drive_files"],
    "my_mcp_server": ["mcp_tool_one", "mcp_tool_two"],
}


def test_shortlist_set_says_it_is_not_everything():
    text = describe_set("supabase", SETS["supabase"], SETS)
    assert "shortlist" in text
    assert "supabase_*" in text
    assert "(3)" in text


def test_sub_set_names_its_nouns_without_the_integration():
    text = describe_set("supabase_storage", SETS["supabase_storage"], SETS)
    assert text.startswith("6 actions:")
    assert "buckets" in text and "files" in text and "signed_url" in text
    assert "supabase" not in text
    # singular and plural of one noun appear once
    assert text.count("bucket") == 1


def test_es_plurals_collapse():
    text = describe_set("supabase_branches", SETS["supabase_branches"], SETS)
    assert text == "2 actions: branches"


def test_set_without_umbrella_still_describes_its_actions():
    text = describe_set("my_mcp_server", SETS["my_mcp_server"], SETS)
    assert text.startswith("2 actions:")
    assert "Custom action set" not in text


def test_long_noun_lists_are_capped():
    many = {"x_big": [f"list_x_thing{i}" for i in range(10)], "x": ["list_x_a"]}
    text = describe_set("x_big", many["x_big"], many)
    assert text.endswith(", …")
    assert text.count(",") == 6
