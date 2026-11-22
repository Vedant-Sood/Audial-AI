"""The stole firmware's motor finder (firmware/kandha/motor_map.h), run on the host.

The wizard buzzes GPIO 8-11 one at a time and saves which zone each one is. Its logic is plain
C++, so it is compiled here against small stand-ins for the Arduino APIs (tests/firmware/) and
driven with scripted answers. This checks the logic only; feeling the motors needs the stole.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

HERE = Path(__file__).parent / "firmware"


@pytest.mark.skipif(not (shutil.which("g++") or shutil.which("c++")), reason="needs a C++17 compiler")
def test_motor_wizard_finds_saves_and_reloads_the_map(tmp_path):
    compiler = shutil.which("g++") or shutil.which("c++")
    exe = tmp_path / "motor_map_test"
    build = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", f"-I{HERE}", "-o", str(exe), str(HERE / "test_motor_map.cpp")],
                           capture_output=True, text=True)
    assert build.returncode == 0, build.stderr
    run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0 and "motor map OK" in run.stdout, run.stdout + run.stderr
