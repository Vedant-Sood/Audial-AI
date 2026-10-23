"""The Kandha Stole Bluetooth link (bleak and its platform backend) inside a PyInstaller build.

`collect()` is what AccessibilityAI.spec and hooks/hook-bleak.py call. It gathers bleak, the backend
bleak needs on this platform and their licence metadata, and it stops the build with a clear message
when any of them is missing. Before, a build machine without bleak quietly produced a Kandha whose
"Real Bluetooth" setting could only say "No module named 'bleak'".

`check_payload()` is the acceptance check on a built or installed PyInstaller folder:

    python packaging/kandha_bluetooth.py --payload dist/AccessibilityAI --os windows

It reads the module archive inside the Kandha executable and the extension modules and metadata
under _internal, prints a JSON report and exits 1 when anything the link needs is missing.
"""
import argparse
from importlib.util import find_spec
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
LICENCES = Path(__file__).resolve().parent / "licenses"

# What bleak imports for its backend on each platform. "modules" must be importable on the build
# machine and frozen into the payload; "extensions" are compiled modules that live as files under
# _internal; "packages" are walked for every submodule; "distributions" carry the licence metadata
# that ships beside them; "licences" are licence texts a backend's wheels leave out, shipped under
# _internal/licenses.
BACKENDS = {
    "windows": {
        "bleak": ["bleak.backends.winrt.client", "bleak.backends.winrt.scanner"],
        "modules": ["winrt.system", "winrt.runtime", "winrt.windows.devices.bluetooth",
                    "winrt.windows.devices.bluetooth.advertisement",
                    "winrt.windows.devices.bluetooth.genericattributeprofile",
                    "winrt.windows.devices.enumeration", "winrt.windows.devices.radios",
                    "winrt.windows.foundation", "winrt.windows.foundation.collections",
                    "winrt.windows.storage.streams", "typing_extensions"],
        "extensions": ["winrt._winrt", "winrt._winrt_windows_devices_bluetooth",
                       "winrt._winrt_windows_devices_bluetooth_advertisement",
                       "winrt._winrt_windows_devices_bluetooth_genericattributeprofile",
                       "winrt._winrt_windows_devices_enumeration", "winrt._winrt_windows_devices_radios",
                       "winrt._winrt_windows_foundation", "winrt._winrt_windows_foundation_collections",
                       "winrt._winrt_windows_storage_streams"],
        "packages": [],
        "dynamic_libs": ["winrt"],              # winrt-runtime carries msvcp140.dll beside its modules
        "distributions": ["winrt-runtime", "winrt-windows-devices-bluetooth",
                          "winrt-windows-devices-bluetooth-advertisement",
                          "winrt-windows-devices-bluetooth-genericattributeprofile",
                          "winrt-windows-devices-enumeration", "winrt-windows-devices-radios",
                          "winrt-windows-foundation", "winrt-windows-foundation-collections",
                          "winrt-windows-storage-streams", "typing-extensions"],
        "licences": ["pywinrt-LICENSE.txt"],     # the winrt-* wheels carry no licence file
    },
    "linux": {
        "bleak": ["bleak.backends.bluezdbus.client", "bleak.backends.bluezdbus.scanner"],
        "modules": ["dbus_fast", "dbus_fast.aio", "dbus_fast.auth", "dbus_fast.message", "dbus_fast.service"],
        "extensions": [],
        "packages": ["dbus_fast"],              # compiled submodules import each other
        "dynamic_libs": [],
        "distributions": ["dbus-fast"],
        "licences": [],
    },
    "macos": {
        "bleak": ["bleak.backends.corebluetooth.client", "bleak.backends.corebluetooth.scanner"],
        "modules": ["objc", "CoreBluetooth", "Foundation", "libdispatch"],
        "extensions": [],
        "packages": [],
        "dynamic_libs": [],
        "distributions": ["pyobjc-core", "pyobjc-framework-CoreBluetooth", "pyobjc-framework-libdispatch"],
        "licences": [],
    },
}


def platform_name(platform=None):
    platform = platform or sys.platform
    if platform.startswith("win"):
        return "windows"
    return "macos" if platform == "darwin" else "linux"


def _importable(name, find):
    try:
        return find(name) is not None
    except (ImportError, ValueError):          # a missing parent package raises instead of returning None
        return False


def missing(platform=None, find=find_spec):
    """Modules the Bluetooth link needs on `platform` that this Python cannot import."""
    backend = BACKENDS[platform_name(platform)]
    if not _importable("bleak", find):
        return ["bleak"]
    return [name for name in backend["bleak"] + backend["modules"] if not _importable(name, find)]


def refusal(platform, lacking):
    return (f"Kandha build stopped: the Kandha Stole Bluetooth link needs {', '.join(lacking)} on {platform}, "
            "and this Python cannot import it. Install the pinned version with "
            "`python -m pip install -r requirements.txt` (bleak brings its platform backend) and build again.")


def collect(platform=None, find=find_spec):
    """(datas, binaries, hiddenimports) for bleak and its backend; SystemExit when anything is missing."""
    from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs, collect_submodules, copy_metadata
    platform = platform_name(platform)
    lacking = missing(platform, find)
    if lacking:
        raise SystemExit(refusal(platform, lacking))
    backend = BACKENDS[platform]
    datas, binaries, hiddenimports = collect_all("bleak")
    datas += copy_metadata("bleak")
    hiddenimports += backend["bleak"] + backend["modules"] + backend["extensions"]
    for package in backend["packages"]:
        hiddenimports += collect_submodules(package)
    for package in backend["dynamic_libs"]:
        binaries += collect_dynamic_libs(package)
    for distribution in backend["distributions"]:
        try:
            datas += copy_metadata(distribution)
        except Exception as error:              # the licence metadata must ship with the backend
            raise SystemExit(refusal(platform, [distribution]) + f" ({error})") from error
    datas += [(str(LICENCES / name), "licenses") for name in backend["licences"]]
    return datas, binaries, hiddenimports


# ---------------------------------------------------------------------------- payload check
def pyz_modules(executable):
    """Names of the modules frozen into a PyInstaller executable's PYZ archive."""
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(executable))
    names = [name for name in archive.toc if name.endswith(".pyz") or name.startswith("PYZ")]
    if not names:
        raise ValueError(f"{executable} has no PYZ module archive")
    modules = set()
    for name in names:
        modules |= set(archive.open_embedded_archive(name).toc)
    return modules


def _extension_on_disk(internal, module):
    folder = internal.joinpath(*module.split(".")[:-1])
    leaf = module.split(".")[-1]
    return folder.is_dir() and any(re.fullmatch(rf"{re.escape(leaf)}(\.[\w-]+)?\.(pyd|so)", path.name)
                                   for path in folder.iterdir())


def _dist_info(internal, distribution):
    canonical = re.sub(r"[-_.]+", "_", distribution).lower()
    for path in internal.glob("*.dist-info"):
        name, _, version = path.name[:-len(".dist-info")].rpartition("-")
        if re.sub(r"[-_.]+", "_", name).lower() == canonical:
            return version
    return None


def pinned_version(requirements=ROOT / "requirements.txt"):
    """The bleak version requirements.txt pins, or None."""
    try:
        text = Path(requirements).read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"^bleak==([\w.]+)\s*$", text, re.M)
    return match.group(1) if match else None


def check_payload(payload, platform=None, modules=None, expect_version=None):
    """Report what the Bluetooth link needs and does not find in a PyInstaller folder."""
    platform = platform_name(platform)
    payload = Path(payload)
    internal = payload / "_internal"
    backend = BACKENDS[platform]
    report = {"payload": str(payload), "platform": platform, "missing": []}
    if modules is None:
        executable = payload / ("Kandha.exe" if platform == "windows" else "Kandha")
        if not executable.is_file():
            report["missing"].append(executable.name)
            modules = set()
        else:
            modules = pyz_modules(executable)
    for module in ["bleak"] + backend["bleak"] + backend["modules"]:
        if module not in modules and not _extension_on_disk(internal, module):
            report["missing"].append(module)
    for module in backend["extensions"]:
        if not _extension_on_disk(internal, module):
            report["missing"].append(module)
    report["bleak_version"] = _dist_info(internal, "bleak")
    for distribution in ["bleak"] + backend["distributions"]:
        if _dist_info(internal, distribution) is None:
            report["missing"].append(f"{distribution} metadata")
    for name in backend["licences"]:
        if not (internal / "licenses" / name).is_file():
            report["missing"].append(f"licenses/{name}")
    expect_version = expect_version or pinned_version()
    if expect_version and report["bleak_version"] not in (None, expect_version):
        report["missing"].append(f"bleak {expect_version} (found {report['bleak_version']})")
    report["ok"] = not report["missing"]
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--payload", type=Path, required=True, help="the PyInstaller COLLECT folder (built or installed)")
    parser.add_argument("--os", dest="platform", choices=sorted(BACKENDS), help="default: this machine")
    parser.add_argument("--expect-version", help="default: the bleak pin in requirements.txt")
    parser.add_argument("--output", type=Path, help="also write the JSON report here")
    args = parser.parse_args(argv)
    report = check_payload(args.payload, args.platform, expect_version=args.expect_version)
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text, flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
