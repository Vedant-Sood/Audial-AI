"""Kandha packaging: the Bluetooth link ships, the Start-menu guide opens on stock Windows, release checksums."""
import hashlib
from html.parser import HTMLParser
import importlib.metadata
import importlib.util
import inspect
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def helper(name):
    """A module from packaging/ (loaded by path: the `packaging` library owns that import name)."""
    found = importlib.util.spec_from_file_location(name, ROOT / "packaging" / f"{name}.py")
    module = importlib.util.module_from_spec(found)
    found.loader.exec_module(module)
    return module


def pins(path):
    pinned = {}
    for line in (ROOT / path).read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9_.-]+)==([^\s;#]+)", line.strip())
        if match:
            pinned[re.sub(r"[-_.]+", "-", match.group(1)).lower()] = match.group(2)
    return pinned


# ---------------------------------------------------------------------------- Bluetooth link (bleak)
def test_bleak_is_pinned_where_the_windows_and_linux_builds_install_from():
    windows, linux = pins("requirements.txt"), pins("requirements-cloud.lock")
    assert "bleak" in windows, "the Windows workflow and setup install requirements.txt; bleak must be in it"
    assert linux.get("bleak") == windows["bleak"]
    assert "dbus-fast" in linux                           # bleak's Linux backend, locked too
    workflow = (ROOT / ".github/workflows/windows-release.yml").read_text(encoding="utf-8")
    assert "-r requirements.txt" in workflow


def test_bleak_and_its_platform_backend_really_import():
    bluetooth = helper("kandha_bluetooth")
    assert bluetooth.missing() == []
    assert importlib.metadata.version("bleak") == pins("requirements.txt")["bleak"]
    from bleak import BleakClient, BleakScanner
    # what app/kandha/bridge.py's BleakBackend relies on
    assert "return_adv" in inspect.signature(BleakScanner.discover).parameters
    client = inspect.signature(BleakClient.__init__).parameters
    assert {"disconnected_callback", "timeout"} <= set(client)
    assert "response" in inspect.signature(BleakClient.write_gatt_char).parameters


def test_a_build_without_bleak_or_its_backend_stops_with_a_message():
    pytest.importorskip("PyInstaller")
    bluetooth = helper("kandha_bluetooth")
    with pytest.raises(SystemExit) as stopped:
        bluetooth.collect("windows", find=lambda name: None)
    assert "bleak" in str(stopped.value) and "requirements.txt" in str(stopped.value)

    def no_radios(name):
        return None if name == "winrt.windows.devices.radios" else object()

    assert bluetooth.missing("windows", find=no_radios) == ["winrt.windows.devices.radios"]
    with pytest.raises(SystemExit, match="winrt.windows.devices.radios"):
        bluetooth.collect("windows", find=no_radios)


def test_a_windows_build_collects_the_winrt_backend_its_metadata_and_licence(monkeypatch):
    hooks = pytest.importorskip("PyInstaller.utils.hooks")
    bluetooth = helper("kandha_bluetooth")
    metadata = []
    monkeypatch.setattr(hooks, "collect_all", lambda name: ([("bleak-data", "bleak")], [], ["bleak.exc"]))
    monkeypatch.setattr(hooks, "copy_metadata", lambda name: metadata.append(name) or [(f"{name}.dist-info", ".")])
    monkeypatch.setattr(hooks, "collect_dynamic_libs", lambda name: [(f"{name}/msvcp140.dll", name)])
    monkeypatch.setattr(hooks, "collect_submodules", lambda name: pytest.fail("nothing to walk on Windows"))
    datas, binaries, hiddenimports = bluetooth.collect("windows", find=lambda name: object())
    windows = bluetooth.BACKENDS["windows"]
    assert metadata == ["bleak"] + windows["distributions"]
    assert set(windows["bleak"] + windows["modules"] + windows["extensions"]) <= set(hiddenimports)
    assert ("winrt/msvcp140.dll", "winrt") in binaries
    assert (str(bluetooth.LICENCES / "pywinrt-LICENSE.txt"), "licenses") in datas


def test_the_spec_no_longer_skips_bleak_quietly():
    spec = (ROOT / "packaging/AccessibilityAI.spec").read_text(encoding="utf-8")
    assert "find_spec('bleak')" not in spec
    assert "packaging_module('kandha_bluetooth').collect()" in spec
    assert "'bleak'}" not in spec                          # its metadata is no longer optional


# ---------------------------------------------------------------------------- legacy portable ZIP (any build host)
def portable_script():
    found = importlib.util.spec_from_file_location("package_windows_portable",
                                                   ROOT / "scripts" / "package_windows_portable.py")
    module = importlib.util.module_from_spec(found)
    found.loader.exec_module(module)
    return module


def normalised(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def test_the_portable_zip_fetches_bleak_alone_and_lists_its_winrt_backend(tmp_path):
    from packaging.requirements import Requirement
    portable = portable_script()
    bleak = pins("requirements.txt")["bleak"]
    resolved, no_deps = portable.portable_requirements(ROOT)
    # pip reads bleak's markers for the build host (dbus-fast on Linux, no WinRT), so it is fetched alone
    assert no_deps == [f"bleak=={bleak}"]
    names = {portable.requirement_name(line) for line in resolved} - {None}
    assert "bleak" not in names and "dbus-fast" not in names
    core = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert all(line in resolved for line in core if portable.requirement_name(line) not in (None, "bleak"))

    # requirements-portable.txt lists the backend the Windows build collects, from one PyWinRT release
    listed = pins("requirements-portable.txt")
    winrt = {name: version for name, version in listed.items() if name.startswith("winrt-")}
    windows = helper("kandha_bluetooth").BACKENDS["windows"]["distributions"]
    assert set(winrt) | {"typing-extensions"} == {normalised(name) for name in windows}
    assert "typing-extensions" in names and len(set(winrt.values())) == 1

    # ...and it is exactly what this bleak asks for on Windows with the bundled CPython, at versions it accepts
    assert importlib.metadata.version("bleak") == bleak
    python = re.search(r"/python/([\d.]+)/", portable.PYTHON_URL).group(1)
    windows_cpython = {"sys_platform": "win32", "platform_system": "Windows", "os_name": "nt",
                       "platform_machine": "AMD64", "implementation_name": "cpython",
                       "platform_python_implementation": "CPython", "python_full_version": python,
                       "python_version": ".".join(python.split(".")[:2]), "extra": ""}
    needed = {}
    for text in importlib.metadata.requires("bleak"):
        requirement = Requirement(text)
        if requirement.marker is None or requirement.marker.evaluate(windows_cpython):
            needed[normalised(requirement.name)] = requirement.specifier
    assert set(needed) == set(winrt), "bleak's Windows dependencies changed; update requirements-portable.txt"
    for name, specifier in needed.items():
        assert specifier.contains(winrt[name]), f"{name}=={winrt[name]} does not satisfy bleak's {specifier}"

    # both pip passes fetch Windows x64 CPython 3.12 wheels; only bleak skips dependency resolution
    resolve, alone = portable.pip_downloads(tmp_path / "wheels", tmp_path, tmp_path / "listing.txt", no_deps)
    for command in (resolve, alone):
        assert "--only-binary=:all:" in command and command[command.index("--platform") + 1] == "win_amd64"
        assert command[command.index("--python-version") + 1] == "312"
        assert command[command.index("--dest") + 1] == str(tmp_path / "wheels")
    assert "--no-deps" not in resolve and resolve[-2:] == ["-r", str(tmp_path / "listing.txt")]
    assert alone[-2:] == ["--no-deps", f"bleak=={bleak}"]


def test_the_portable_requirement_reader_expands_includes_and_keeps_bleak_apart(tmp_path):
    portable = portable_script()
    (tmp_path / "requirements.txt").write_text("numpy==2.3.5\n# a comment\nBleak == 3.0.2  # stole link\n")
    (tmp_path / "more.txt").write_text("pywin32>=306\nbleak-pythonista>=0.1.1\n")
    (tmp_path / "requirements-portable.txt").write_text(
        "-r requirements.txt\n--requirement=more.txt\nwinrt-runtime==3.2.1\n")
    resolved, no_deps = portable.portable_requirements(tmp_path)
    assert no_deps == ["Bleak == 3.0.2"]
    assert resolved == ["numpy==2.3.5", "# a comment", "pywin32>=306", "bleak-pythonista>=0.1.1",
                        "winrt-runtime==3.2.1"]
    assert portable.pip_downloads(tmp_path, tmp_path, tmp_path / "listing.txt", [])[-1][-1] == \
        str(tmp_path / "listing.txt")                    # nothing to fetch alone: one pass


def fake_payload(tmp_path, platform="windows", version="3.0.2", drop=()):
    bluetooth = helper("kandha_bluetooth")
    backend = bluetooth.BACKENDS[platform]
    internal = tmp_path / "_internal"
    internal.mkdir(parents=True)
    for module in backend["extensions"]:
        if module not in drop:
            folder = internal.joinpath(*module.split(".")[:-1])
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{module.split('.')[-1]}.cp312-win_amd64.pyd").write_bytes(b"")
    for distribution in ["bleak"] + backend["distributions"]:
        if distribution not in drop:
            name = re.sub(r"[-_.]+", "_", distribution)
            (internal / f"{name}-{version if distribution == 'bleak' else '1.0'}.dist-info").mkdir()
    for licence in backend["licences"]:
        if f"licenses/{licence}" not in drop:
            (internal / "licenses").mkdir(exist_ok=True)
            (internal / "licenses" / licence).write_text("MIT")
    modules = {"bleak", *backend["bleak"], *backend["modules"]} - set(drop)
    return bluetooth, modules


def test_the_payload_check_passes_a_complete_windows_payload(tmp_path):
    bluetooth, modules = fake_payload(tmp_path)
    report = bluetooth.check_payload(tmp_path, "windows", modules=modules, expect_version="3.0.2")
    assert report["ok"] and report["missing"] == [] and report["bleak_version"] == "3.0.2"


@pytest.mark.parametrize("drop", ["bleak", "winrt.windows.devices.bluetooth", "winrt._winrt_windows_devices_bluetooth",
                                  "winrt-runtime", "licenses/pywinrt-LICENSE.txt"])
def test_the_payload_check_names_what_is_missing(tmp_path, drop):
    bluetooth, modules = fake_payload(tmp_path, drop=(drop,))
    report = bluetooth.check_payload(tmp_path, "windows", modules=modules, expect_version="3.0.2")
    assert not report["ok"] and any(drop in item for item in report["missing"])


def test_the_winrt_licence_text_the_wheels_leave_out_ships_and_is_noticed():
    bluetooth = helper("kandha_bluetooth")
    for platform in bluetooth.BACKENDS.values():
        for name in platform["licences"]:
            text = (bluetooth.LICENCES / name).read_text(encoding="utf-8")
            assert "MIT License" in text and "Permission is hereby granted" in text
    notices = (ROOT / "LICENSE_NOTICES.md").read_text(encoding="utf-8")
    row = next(line for line in notices.splitlines() if line.startswith("| bleak"))
    for name in ("winrt-runtime", "msvcp140.dll", "dbus-fast", "pywinrt-LICENSE.txt"):
        assert name in row


def test_the_payload_check_rejects_a_different_bleak_than_the_pin(tmp_path):
    bluetooth, modules = fake_payload(tmp_path, version="0.22.3")
    report = bluetooth.check_payload(tmp_path, "windows", modules=modules, expect_version="3.0.2")
    assert report["missing"] == ["bleak 3.0.2 (found 0.22.3)"]


def test_the_payload_check_without_a_kandha_executable_fails(tmp_path):
    bluetooth = helper("kandha_bluetooth")
    (tmp_path / "_internal").mkdir()
    assert bluetooth.main(["--payload", str(tmp_path), "--os", "linux", "--expect-version", "3.0.2"]) == 1


@pytest.mark.skipif(not (ROOT / "dist/AccessibilityAI/Kandha").is_file(), reason="no local Linux PyInstaller build")
def test_the_payload_check_reads_the_modules_frozen_into_kandha():
    pytest.importorskip("PyInstaller")
    modules = helper("kandha_bluetooth").pyz_modules(ROOT / "dist/AccessibilityAI/Kandha")
    assert "launcher" not in modules and "app.kandha.bridge" in modules


# ---------------------------------------------------------------------------- user guide
class Balance(HTMLParser):
    VOID = {"meta", "br", "hr", "img", "link", "input"}

    def __init__(self):
        super().__init__()
        self.stack, self.errors, self.text = [], [], []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        else:
            self.errors.append(tag)

    def handle_data(self, data):
        self.text.append(data)


def test_the_user_guide_renders_to_a_page_stock_windows_opens():
    guide = (ROOT / "docs/kandha/USER_GUIDE.md").read_text(encoding="utf-8")
    page = helper("render_user_guide").render(guide)
    assert page.startswith("<!doctype html>") and '<html lang="en">' in page
    assert "<title>Kandha user guide</title>" in page
    parser = Balance()
    parser.feed(page)
    assert parser.errors == [] and parser.stack == []
    body = "".join(parser.text[parser.text.index("Kandha user guide", 1):])
    assert not re.search(r"\*\*|^#+ |^\|.*\|$|^> ", body, re.M)       # no Markdown left as text
    for heading in re.findall(r"^## (.+)$", guide, re.M):
        assert f">{heading}</h2>" in page
    assert page.count("<table>") == len(re.findall(r"^\|[ :|-]+\|$", guide, re.M))
    assert '<th scope="col">' in page
    # offline and private: no script and nothing fetched from the network
    assert "<script" not in page.lower()
    assert not re.search(r"""src=["']?(https?:)?//|url\(["']?(https?:)?//|@import""", page)


def test_the_guide_renderer_escapes_markup_and_unsafe_links():
    render = helper("render_user_guide")
    page = render.render("# T\n\n<script>alert(1)</script> [bad](javascript:alert(1)) [ok](https://example.org/?a=1&b=2)\n")
    assert "<script>alert" not in page and "&lt;script&gt;" in page
    assert 'href="javascript' not in page
    assert '<a href="https://example.org/?a=1&amp;b=2">ok</a>' in page


def test_the_start_menu_guide_entry_opens_the_html_rendering():
    iss = (ROOT / "packaging/kandha-installer.iss").read_text(encoding="utf-8")
    entry = next(line for line in iss.splitlines() if line.startswith('Name: "{group}\\Kandha user guide"'))
    assert 'Filename: "{app}\\_internal\\docs\\kandha\\USER_GUIDE.html"' in entry
    spec = (ROOT / "packaging/AccessibilityAI.spec").read_text(encoding="utf-8")
    assert "render_user_guide" in spec and "'docs/kandha'" in spec


def test_the_guide_renders_to_a_file(tmp_path):
    out = helper("render_user_guide").write(ROOT / "docs/kandha/USER_GUIDE.md", tmp_path / "deep" / "USER_GUIDE.html")
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")


# ---------------------------------------------------------------------------- release checksums
@pytest.mark.skipif(sys.platform == "win32", reason="runs the release job's bash step")
def test_the_kandha_release_publishes_a_sha256_beside_every_asset(tmp_path):
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load((ROOT / ".github/workflows/windows-release.yml").read_text(encoding="utf-8"))
    step = next(s for s in workflow["jobs"]["release-kandha"]["steps"] if s.get("name", "").startswith("Publish"))
    version = "9.9.9"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "python3").write_text(f"#!/bin/sh\necho {version}\n")
    (bin_dir / "gh").write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$GH_ARGS"\n')
    for stub in bin_dir.iterdir():
        stub.chmod(0o755)
    files = {"Kandha-Windows-x64-CPU": [f"Kandha-Setup-{version}.exe", f"Kandha-{version}-windows.zip"],
             "Kandha-Windows-x64-NVIDIA": [f"Kandha-Setup-{version}.exe"],
             "firmware": [f"kandha-stole-firmware-{version}.zip"]}
    for folder, names in files.items():
        where = tmp_path / "release-assets" / folder
        where.mkdir(parents=True)
        for name in names:
            (where / name).write_bytes(f"{folder}/{name}".encode())
            digest = hashlib.sha256((where / name).read_bytes()).hexdigest()
            (where / f"{name}.sha256").write_bytes(f"{digest}  {name}\r\n".encode())   # PowerShell writes CRLF
    env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}", GITHUB_REF_NAME=f"kandha-v{version}",
               GH_ARGS=str(tmp_path / "gh-args.txt"))
    run = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    published = sorted(p.name for p in (tmp_path / "publish").iterdir())
    assets = [f"Kandha-{version}-windows.zip", f"Kandha-Setup-{version}-NVIDIA.exe", f"Kandha-Setup-{version}.exe",
              f"kandha-stole-firmware-{version}.zip"]
    assert published == sorted(assets + [a + ".sha256" for a in assets] + ["SHA256SUMS.txt"])
    for asset in assets:
        digest = hashlib.sha256((tmp_path / "publish" / asset).read_bytes()).hexdigest()
        assert (tmp_path / "publish" / f"{asset}.sha256").read_text() == f"{digest}  {asset}\n"
    uploaded = (tmp_path / "gh-args.txt").read_text().split("\n")
    assert all(f"publish/{name}" in uploaded for name in published)

    # a download that no longer matches the build job's checksum stops the release
    (tmp_path / "release-assets/firmware" / f"kandha-stole-firmware-{version}.zip").write_bytes(b"tampered")
    rerun = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", f"rm -rf publish; {step['run']}"],
                           cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert rerun.returncode != 0
