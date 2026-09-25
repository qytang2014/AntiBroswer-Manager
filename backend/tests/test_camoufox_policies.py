import json
from pathlib import Path
import pytest
from backend.camoufox_policies import (
    resolve_camoufox_distribution_dir,
    sanitize_camoufox_policies,
    sanitize_camoufox_profile_search_cache,
    get_camoufox_user_prefs,
    sanitize_all_installed_camoufox_kernels,
)

def test_resolve_camoufox_distribution_dir_macos(tmp_path: Path):
    app_macos = tmp_path / "Camoufox.app" / "Contents" / "MacOS" / "camoufox"
    app_macos.parent.mkdir(parents=True)
    app_macos.touch()

    dist = resolve_camoufox_distribution_dir(app_macos)
    expected = tmp_path / "Camoufox.app" / "Contents" / "Resources" / "distribution"
    assert dist == expected
    assert dist.is_dir()


def test_resolve_camoufox_distribution_dir_generic(tmp_path: Path):
    generic_bin = tmp_path / "camoufox" / "camoufox"
    generic_bin.parent.mkdir(parents=True)
    generic_bin.touch()

    dist = resolve_camoufox_distribution_dir(generic_bin)
    expected = tmp_path / "camoufox" / "distribution"
    assert dist == expected
    assert dist.is_dir()


def test_sanitize_camoufox_policies_cleans_unwanted_uninstall_and_dummy_engine(tmp_path: Path):
    dist_dir = tmp_path / "distribution"
    dist_dir.mkdir(parents=True)
    pol_file = dist_dir / "policies.json"

    initial_policies = {
        "policies": {
            "Extensions": {
                "Uninstall": [
                    "google@search.mozilla.org",
                    "bing@search.mozilla.org",
                    "webcompat@mozilla.org",
                    "formautofill@mozilla.org",
                ]
            },
            "SearchEngines": {
                "PreventInstalls": True,
                "Remove": ["Google", "DuckDuckGo", "Bing", "Amazon.com"],
                "Default": "None",
                "Add": [
                    {
                        "Name": "None",
                        "URLTemplate": "http://127.0.0.1",
                    }
                ]
            }
        }
    }
    pol_file.write_text(json.dumps(initial_policies, indent=2))

    res = sanitize_camoufox_policies(dist_dir, default_engine_name="Google")
    assert res is True

    updated = json.loads(pol_file.read_text())
    policies = updated["policies"]

    # 1. Extensions.Uninstall must keep webcompat, google, and bing
    assert "webcompat@mozilla.org" not in policies["Extensions"]["Uninstall"]
    assert "google@search.mozilla.org" not in policies["Extensions"]["Uninstall"]
    assert "bing@search.mozilla.org" not in policies["Extensions"]["Uninstall"]
    assert "formautofill@mozilla.org" in policies["Extensions"]["Uninstall"]

    # 2. SearchEngines
    search = policies["SearchEngines"]
    assert search["PreventInstalls"] is False
    assert search["Default"] == "Google"
    # Dummy engine removed
    assert not any(e.get("Name") == "None" for e in search["Add"])
    # Target engine added
    google_entry = next((e for e in search["Add"] if e.get("Name") == "Google"), None)
    assert google_entry is not None
    assert "{searchTerms}" in google_entry["URLTemplate"]


def test_sanitize_camoufox_policies_custom_engine(tmp_path: Path):
    dist_dir = tmp_path / "distribution"
    dist_dir.mkdir(parents=True)

    res = sanitize_camoufox_policies(
        dist_dir,
        default_engine_name="DuckDuckGo",
        default_engine_url="https://duckduckgo.com/?q=%s",
    )
    assert res is True

    pol_file = dist_dir / "policies.json"
    updated = json.loads(pol_file.read_text())
    search = updated["policies"]["SearchEngines"]
    assert search["Default"] == "DuckDuckGo"
    ddg_entry = next((e for e in search["Add"] if e.get("Name") == "DuckDuckGo"), None)
    assert ddg_entry is not None
    assert ddg_entry["URLTemplate"] == "https://duckduckgo.com/?q={searchTerms}"


def test_sanitize_camoufox_profile_search_cache(tmp_path: Path):
    profile_dir = tmp_path / "profile_camoufox"
    profile_dir.mkdir(parents=True)

    # 1. Create a prefs.js containing stale dummy search engine prefs
    prefs_js = profile_dir / "prefs.js"
    prefs_js.write_text(
        'user_pref("browser.policies.runOncePerModification.removeSearchEngines", "[\'Google\']");\n'
        'user_pref("browser.policies.runOncePerModification.setDefaultSearchEngine", "None");\n'
        'user_pref("browser.policies.applied", true);\n'
        'user_pref("browser.urlbar.placeholderName", "None");\n'
        'user_pref("other.pref", 123);\n'
    )

    # 2. Create a dummy search.json.mozlz4 under 500 bytes
    search_moz = profile_dir / "search.json.mozlz4"
    search_moz.write_bytes(b"mozLz40\0small_dummy_content")

    sanitize_camoufox_profile_search_cache(profile_dir, "Google")

    # Stale prefs removed
    cleaned_text = prefs_js.read_text()
    assert "removeSearchEngines" not in cleaned_text
    assert 'setDefaultSearchEngine", "None"' not in cleaned_text
    assert 'placeholderName", "None"' not in cleaned_text
    assert "browser.policies.applied" in cleaned_text
    assert "other.pref" in cleaned_text

    # Dummy small search.json.mozlz4 deleted so Firefox reconstructs it from policies
    assert not search_moz.exists()


def test_get_camoufox_user_prefs():
    profile = {
        "search_engine_name": "Bing",
        "allow_3p_cookies": True,
    }
    prefs = get_camoufox_user_prefs(
        profile,
        target_os="macos",
        timezone="America/Los_Angeles",
        locale="en-US",
    )
    assert prefs["keyword.enabled"] is True
    assert prefs["browser.urlbar.suggest.searches"] is True
    assert prefs["browser.search.defaultenginename"] == "Bing"
    assert prefs["network.cookie.cookieBehavior"] == 0
    assert prefs["font.name.monospace.x-western"] == "Courier New"
    assert prefs["font.name.sans-serif.x-western"] == "Arial"
    assert prefs["font.name.serif.x-western"] == "Times New Roman"
    assert prefs["roverfox.s.timezone_0"] == "America/Los_Angeles"
    assert prefs["intl.accept_languages"] == "en-US, en"

    profile_no_cookies = {
        "allow_3p_cookies": False,
    }
    prefs_no_cookies = get_camoufox_user_prefs(
        profile_no_cookies,
        target_os="windows",
        timezone="Asia/Tokyo",
        locale="ja-JP",
    )
    assert prefs_no_cookies["network.cookie.cookieBehavior"] == 4
    assert prefs_no_cookies["font.name.monospace.x-western"] == "Consolas"
    assert prefs_no_cookies["roverfox.s.timezone_0"] == "Asia/Tokyo"
    assert prefs_no_cookies["intl.accept_languages"] == "ja-JP, ja"


def test_get_camoufox_recommended_fonts():
    from backend.camoufox_policies import get_camoufox_recommended_fonts

    mac_fonts = get_camoufox_recommended_fonts("macos")
    assert "Menlo" in mac_fonts
    assert "Monaco" in mac_fonts
    assert "Courier New" in mac_fonts

    win_fonts = get_camoufox_recommended_fonts("windows")
    assert "Consolas" in win_fonts
    assert "Courier New" in win_fonts

    linux_fonts = get_camoufox_recommended_fonts("linux")
    assert "monospace" in linux_fonts

