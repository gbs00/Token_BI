import pytest

from scripts.verify_bundle import verify_resources


@pytest.fixture
def bundle(tmp_path):
    app = tmp_path / "Token BI.app"
    for name in ("token-bi-control", "token-bi-backend"):
        internal = app / "Contents/Resources" / f"{name}-runtime/_internal"
        framework = internal / "Python3.framework"
        version = framework / "Versions/3.9"
        version.mkdir(parents=True)
        (version / "Python3").write_bytes(b"library")
        (framework / "Versions/Current").symlink_to("3.9")
        (framework / "Python3").symlink_to("Versions/Current/Python3")
        (internal / "Python3").symlink_to("Python3.framework/Versions/3.9/Python3")
    return app


def test_bundle_counts_library_once_per_runtime(bundle):
    assert verify_resources(bundle)["total"] == len(b"library") * 2


def test_bundle_rejects_dereferenced_python_library(bundle):
    alias = bundle / "Contents/Resources/token-bi-control-runtime/_internal/Python3"
    content = alias.read_bytes()
    alias.unlink()
    alias.write_bytes(content)
    with pytest.raises(AssertionError, match="expanded into copies"):
        verify_resources(bundle)


@pytest.mark.parametrize("target", ["missing", "/etc/hosts"])
def test_bundle_rejects_unsafe_links(bundle, target):
    internal = bundle / "Contents/Resources/token-bi-control-runtime/_internal"
    (internal / "bad-link").symlink_to(target)
    with pytest.raises(AssertionError, match="Broken|escapes"):
        verify_resources(bundle)


def test_bundle_rejects_retired_console(bundle):
    (bundle / "Contents/Resources/control_panel.html").touch()
    with pytest.raises(AssertionError, match="Retired console"):
        verify_resources(bundle)


def test_bundle_size_budget_is_enforced(bundle, monkeypatch):
    monkeypatch.setattr("scripts.verify_bundle.MAX_BUNDLE_BYTES", 1)
    with pytest.raises(AssertionError, match="byte budget"):
        verify_resources(bundle)
