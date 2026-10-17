"""resume.py: where a chat's browser left off (its open pages and the last
picture of the page on screen), kept in the session's profile folder. Pure
file tests; the browser reopening its pages is in test_mini_browser_fleet.py.
"""

from __future__ import annotations

import json

from app.mini_browser import resume
from app.mini_browser.resume import LastFrame, Page, Pages


def frame(url: str) -> LastFrame:
    return LastFrame(url=url, title="T", width=1280, height=800, image="AAAA")


def test_pages_round_trip_and_leave_no_temporary_file(tmp_path):
    pages = Pages(
        pages=(Page("https://a.example/", "A"), Page("https://b.example/x?y=1", "B")),
        viewed=1,
    )
    resume.save_pages(tmp_path, pages)
    assert resume.load_pages(tmp_path) == pages
    assert sorted(p.name for p in tmp_path.iterdir()) == [resume.PAGES_FILE]

    resume.save_pages(tmp_path, Pages(pages=()))  # everything was closed
    assert resume.load_pages(tmp_path) == Pages(pages=(), viewed=0)


def test_nothing_saved_when_missing_unreadable_or_malformed(tmp_path):
    assert resume.load_pages(tmp_path) is None
    assert resume.load_last_frame(tmp_path) is None
    target = tmp_path / resume.PAGES_FILE
    for content in (
        "not json",
        "[]",
        json.dumps({"pages": "x", "viewed": 0}),
        json.dumps({"pages": [{"url": "", "title": ""}], "viewed": 0}),
        json.dumps({"pages": [{"url": "https://a.example/", "title": 3}], "viewed": 0}),
        json.dumps({"pages": [], "viewed": "0"}),
    ):
        target.write_text(content, encoding="utf-8")
        assert resume.load_pages(tmp_path) is None, content
    frame_file = tmp_path / resume.LAST_FRAME_FILE
    for content in (
        "{",
        json.dumps({"url": "https://a.example/", "title": "", "image": "AAAA"}),
        json.dumps(
            {
                "url": "https://a.example/",
                "title": "",
                "image": "AAAA",
                "width": 0,
                "height": 10,
            }
        ),
    ):
        frame_file.write_text(content, encoding="utf-8")
        assert resume.load_last_frame(tmp_path) is None, content


def test_loading_caps_the_pages_and_mends_the_viewed_index(tmp_path):
    many = [{"url": f"https://a.example/{i}", "title": ""} for i in range(25)]
    (tmp_path / resume.PAGES_FILE).write_text(
        json.dumps({"pages": many, "viewed": 99}), encoding="utf-8"
    )
    loaded = resume.load_pages(tmp_path)
    assert loaded is not None
    assert len(loaded.pages) == resume.MAX_PAGES
    assert loaded.viewed == 0


def test_the_picture_shows_only_the_page_reopened_on_screen(tmp_path):
    resume.save_last_frame(tmp_path, frame("https://a.example/"))
    assert resume.resume_frame(tmp_path) is None  # no pages: nothing reopens

    resume.save_pages(
        tmp_path,
        Pages(
            pages=(Page("https://b.example/", ""), Page("https://a.example/", "")),
            viewed=1,
        ),
    )
    assert resume.resume_frame(tmp_path) == frame("https://a.example/")

    # An agent browsed on with nobody watching: the picture is out of date.
    resume.save_pages(tmp_path, Pages(pages=(Page("https://c.example/", ""),)))
    assert resume.resume_frame(tmp_path) is None


def test_the_ui_message_carries_an_inline_jpeg_or_nothing():
    assert resume.ui_payload("chat-a", None) == {"sessionId": "chat-a", "image": None}
    payload = resume.ui_payload("chat-a", frame("https://a.example/"))
    assert payload == {
        "sessionId": "chat-a",
        "image": "data:image/jpeg;base64,AAAA",
        "width": 1280,
        "height": 800,
        "url": "https://a.example/",
        "title": "T",
    }
