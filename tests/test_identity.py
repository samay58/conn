"""T1: the grant-target resolver names the artifact TCC actually checks.
The 2026-07-08 drive proved the cost of getting this wrong: doctor named
bin/python3.14, the grant went there, and the daemon (whose real image is
Python.app inside the framework) stayed untrusted.
"""

import os
import sys

import pytest

from conn.identity import app_bundle_of, describe_identity, grant_target, process_image_path

FRAMEWORK_IMAGE = (
    "/opt/homebrew/Cellar/python@3.14/3.14.6/Frameworks/Python.framework/"
    "Versions/3.14/Resources/Python.app/Contents/MacOS/Python"
)
FRAMEWORK_BUNDLE = (
    "/opt/homebrew/Cellar/python@3.14/3.14.6/Frameworks/Python.framework/"
    "Versions/3.14/Resources/Python.app"
)


def test_app_bundle_of_framework_python_names_python_app():
    assert app_bundle_of(FRAMEWORK_IMAGE) == FRAMEWORK_BUNDLE


def test_app_bundle_of_regular_app():
    assert app_bundle_of("/Applications/Conn.app/Contents/MacOS/Conn") == "/Applications/Conn.app"


def test_app_bundle_of_nested_bundle_picks_innermost():
    image = "/Applications/Big.app/Contents/Helpers/Helper.app/Contents/MacOS/Helper"
    assert app_bundle_of(image) == "/Applications/Big.app/Contents/Helpers/Helper.app"


def test_app_bundle_of_bare_binary_is_none():
    assert app_bundle_of("/opt/homebrew/bin/python3.14") is None


def test_grant_target_prefers_bundle():
    assert grant_target(FRAMEWORK_IMAGE) == FRAMEWORK_BUNDLE


def test_grant_target_bare_binary_is_the_binary():
    assert grant_target("/usr/local/bin/mytool") == "/usr/local/bin/mytool"


def test_grant_target_falls_back_to_executable_when_pidpath_fails(monkeypatch):
    import conn.identity as identity

    monkeypatch.setattr(identity, "process_image_path", lambda pid=None: None)
    assert identity.grant_target() == os.path.realpath(sys.executable)


@pytest.mark.skipif(sys.platform != "darwin", reason="proc_pidpath is macOS-only")
def test_process_image_path_is_a_real_file():
    image = process_image_path()
    assert image is not None
    assert os.path.exists(image)


@pytest.mark.skipif(sys.platform != "darwin", reason="proc_pidpath is macOS-only")
def test_describe_identity_shape():
    identity = describe_identity()
    assert set(identity) == {"executable", "image", "grant_target"}
    assert identity["executable"] == sys.executable
    assert identity["grant_target"]
