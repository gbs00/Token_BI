import pytest

from scripts.verify_bundle import verify_resources


@pytest.fixture
def bundle(tmp_path):
    app = tmp_path / "Token BI.app"
    runtime = app / "Contents/Resources/token-bi-runtime"
    internal = runtime / "_internal"
    framework = internal / "Python3.framework"
    version = framework / "Versions/3.9"
    version.mkdir(parents=True)
    (version / "Python3").write_bytes(b"library")
    (framework / "Versions/Current").symlink_to("3.9")
    (framework / "Python3").symlink_to("Versions/Current/Python3")
    (internal / "Python3").symlink_to("Python3.framework/Versions/3.9/Python3")
    (internal / "base_library.zip").write_bytes(b"stdlib")
    for name in ("token-bi-control", "token-bi-backend"):
        binary = runtime / name
        binary.write_bytes(b"executable")
        binary.chmod(0o755)
    native = app / "Contents/Resources/Token BI Web Session.app/Contents/MacOS/TokenBIWebSession"
    native.parent.mkdir(parents=True)
    native.write_bytes(b"native")
    native.chmod(0o755)
    return app


def test_bundle_counts_one_shared_runtime(bundle):
    sizes = verify_resources(bundle)
    assert sizes["runtime"] == len(b"library") + len(b"stdlib") + len(b"executable") * 2
    assert sizes["total"] == sizes["runtime"] + len(b"native")


def test_bundle_rejects_dereferenced_python_library(bundle):
    alias = bundle / "Contents/Resources/token-bi-runtime/_internal/Python3"
    content = alias.read_bytes()
    alias.unlink()
    alias.write_bytes(content)
    with pytest.raises(AssertionError, match="expanded into copies"):
        verify_resources(bundle)


@pytest.mark.parametrize("target", ["missing", "/etc/hosts"])
def test_bundle_rejects_unsafe_links(bundle, target):
    internal = bundle / "Contents/Resources/token-bi-runtime/_internal"
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


@pytest.mark.parametrize("name", ["playwright", "node"])
def test_bundle_rejects_retired_browser_runtime(bundle, name):
    (bundle / "Contents/Resources" / name).touch()
    with pytest.raises(AssertionError, match="must not ship"):
        verify_resources(bundle)


def test_bundle_requires_native_web_component(bundle):
    native = bundle / "Contents/Resources/Token BI Web Session.app/Contents/MacOS/TokenBIWebSession"
    native.unlink()
    with pytest.raises(AssertionError, match="Missing native"):
        verify_resources(bundle)


@pytest.mark.parametrize("name", ["token-bi-control", "token-bi-backend"])
def test_bundle_requires_both_service_entrypoints(bundle, name):
    (bundle / "Contents/Resources/token-bi-runtime" / name).unlink()
    with pytest.raises(AssertionError, match="Missing service"):
        verify_resources(bundle)


@pytest.mark.parametrize("name", ["token-bi-control-runtime", "token-bi-backend-runtime"])
def test_bundle_rejects_old_separate_runtimes(bundle, name):
    (bundle / "Contents/Resources" / name).mkdir()
    with pytest.raises(AssertionError, match="Separate runtime"):
        verify_resources(bundle)


def test_bundle_rejects_extra_python_framework(bundle):
    (bundle / "Contents/Resources/extra/Python3.framework").mkdir(parents=True)
    with pytest.raises(AssertionError, match="duplicate Python"):
        verify_resources(bundle)


def test_bundle_rejects_extra_base_library(bundle):
    extra = bundle / "Contents/Resources/extra/base_library.zip"
    extra.parent.mkdir()
    extra.write_bytes(b"stdlib")
    with pytest.raises(AssertionError, match="base_library"):
        verify_resources(bundle)
