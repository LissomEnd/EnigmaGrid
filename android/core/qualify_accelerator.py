"""Host checks for GPU adapter fallback, batching duty and parallel receipt parity.

These use controlled backends; they do not qualify a physical GPU driver.
"""
import argparse
import pathlib
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("--jdk", type=pathlib.Path, required=True)
args = parser.parse_args()
core = pathlib.Path(__file__).resolve().parent
checks = ["ControlChecks", "CpuRowsChecks", "AdaptiveRowsChecks", "BatchRowsChecks", "ParallelChecks"]
with tempfile.TemporaryDirectory(prefix="enigmagrid-accelerator-") as output:
    sources = list((core / "src/main/java/org/enigmagrid/core").glob("*.java"))
    subprocess.run([str(args.jdk / "bin/javac.exe"), "-d", output,
                    *map(str, sources), *[str(core / (name + ".java")) for name in checks]],
                   check=True, timeout=60)
    for name in checks:
        subprocess.run([str(args.jdk / "bin/java.exe"), "-cp", output, name],
                       check=True, timeout=60)
