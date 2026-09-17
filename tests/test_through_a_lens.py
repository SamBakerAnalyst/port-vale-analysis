"""Through a Lens match galleries for Meeting Front Pages."""

from __future__ import annotations

from app.through_a_lens import (
    album_key_from_uri,
    extract_node_id_for_url_path,
    extract_public_api_key,
    gallery_web_url,
    photo_from_album_image,
)


def test_gallery_web_url_inserts_the_public_pvfc_node():
    assert gallery_web_url("/PVFC/Season-2627/Matches/League-/Oldham") == (
        "https://www.throughalensphotography.com/PVFC/n-ns9wjB/Season-2627/Matches/League-/Oldham"
    )
    assert gallery_web_url("/PVFC/n-ns9wjB/Season-2627/Matches/League-").endswith(
        "/PVFC/n-ns9wjB/Season-2627/Matches/League-"
    )


def test_extracts_public_node_id_and_album_key_from_smugmug_html():
    html = (
        'var SM = {env: {"apiKey":"publicclientkey1234567890ab"'
        '},"NodeID":"n5j9dc","UrlPath":"\\/PVFC\\/Season-2627\\/Matches\\/League-"}'
    )
    assert extract_public_api_key(html) == "publicclientkey1234567890ab"
    assert extract_node_id_for_url_path(html, "/PVFC/Season-2627/Matches/League-") == "n5j9dc"
    assert album_key_from_uri("/api/v2/album/HNVmmT?_shorturis=") == "HNVmmT"


def test_photo_payload_uses_proxy_and_never_leaks_api_key():
    image = {
        "ImageKey": "gwq3Czg",
        "FileName": "Oldham (A)-1.jpg",
        "ArchivedUri": "https://photos.smugmug.com/oldham-1.jpg",
        "ThumbnailUrl": "https://photos.smugmug.com/oldham-1-th.jpg",
        "WebUri": "https://www.throughalensphotography.com/PVFC/n-ns9wjB/i-gwq3Czg",
    }
    expansions = {
        "/api/v2/image/gwq3Czg-0!sizedetails": {
            "ImageSizeDetails": {
                "ImageSizeX2Large": {
                    "Url": "https://photos.smugmug.com/oldham-1-x2.jpg",
                    "Width": 1280,
                    "Height": 960,
                },
                "ImageSizeLarge": {
                    "Url": "https://photos.smugmug.com/oldham-1-l.jpg",
                    "Width": 800,
                    "Height": 600,
                },
            }
        }
    }
    row = photo_from_album_image(
        image, expansions=expansions, match_name="Oldham (A)", kind="action"
    )
    assert row is not None
    assert row["id"] == "vale-gwq3Czg"
    assert row["source"] == "through-a-lens"
    assert row["url"] == "https://photos.smugmug.com/oldham-1-x2.jpg"
    assert "image-proxy?url=" in row["proxyUrl"]
    assert "apiKey" not in str(row).casefold()
    assert "publicclientkey" not in str(row)


def test_child_folder_lookup_matches_url_path_or_name():
    from app.through_a_lens import _child_node_id

    nodes = [
        {"Name": "Matches", "NodeID": "7CwwpL", "UrlPath": "/PVFC/Season-2627/Matches"},
        {"Name": "Player Headshots / Media Day", "NodeID": "KtpL3t", "UrlPath": "/PVFC/Season-2627/Player-Headshots-Media-Day"},
    ]
    assert _child_node_id(nodes, url_path="/PVFC/Season-2627/Matches") == "7CwwpL"
    assert _child_node_id(nodes, name="Player Headshots / Media Day") == "KtpL3t"


def test_meeting_front_pages_html_has_through_a_lens_picker():
    from app.paths import STANDALONE_DIR, STATIC_DIR

    html = (STANDALONE_DIR / "meeting-front-pages.html").read_text(encoding="utf-8")
    js = (STATIC_DIR / "meeting-front-pages.js").read_text(encoding="utf-8")
    assert 'data-photo-source="vale"' in html
    assert 'id="valeMatches"' in html
    assert "Through a Lens" in html
    assert "/api/meeting-front-pages/vale-photos" in js
    assert "loadValeGalleries" in js
    assert "loadValePhotos" in js
