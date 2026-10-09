"""Host-only deterministic tests for the Android automatic CPU/GPU profile gate."""
import argparse
import pathlib
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("--jdk", required=True)
args = parser.parse_args()
root = pathlib.Path(__file__).resolve().parents[1]
jdk = pathlib.Path(args.jdk) / "bin"

with tempfile.TemporaryDirectory(prefix="enigma-auto-solver-") as temporary:
    output = pathlib.Path(temporary)
    package = output / "stubs/org/enigmagrid/android"
    package.mkdir(parents=True)
    (package / "GpuProcess.java").write_text(
        "package org.enigmagrid.android; final class GpuProcess {"
        "int[] rows(int[] input){throw new AssertionError();}"
        "int[] solve(int[] input){throw new AssertionError();}"
        "int[] solveKeys(int[] input){throw new AssertionError();}}",
        encoding="utf-8",
    )
    (package / "SolverQualification.java").write_text(
        'package org.enigmagrid.android; final class SolverQualification {static String key(){return "test-scope";}}',
        encoding="utf-8",
    )
    sources = list((root / "core/src/main/java/org/enigmagrid/core").glob("*.java"))
    sources.extend([
        root / "app/src/main/java/org/enigmagrid/android/AutomaticSolverQualification.java",
        root / "core/AutomaticSolverQualificationChecks.java",
        package / "GpuProcess.java",
        package / "SolverQualification.java",
    ])
    subprocess.run([str(jdk / "javac.exe"), "-encoding", "UTF-8", "-d", str(output), *map(str, sources)], check=True)
    subprocess.run([str(jdk / "java.exe"), "-cp", str(output), "org.enigmagrid.android.AutomaticSolverQualificationChecks"], check=True)
