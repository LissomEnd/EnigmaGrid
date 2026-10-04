"""Real JNI loader absence and CPU fallback; does not qualify a physical driver."""
import argparse
import pathlib
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("--jdk", type=pathlib.Path, required=True)
args = parser.parse_args()
core = pathlib.Path(__file__).resolve().parent
backend = core.parent / "app/src/main/java/org/enigmagrid/android/VulkanBackend.java"
with tempfile.TemporaryDirectory(prefix="enigmagrid-no-native-") as folder:
    output = pathlib.Path(folder)
    native = output / "empty-native"
    native.mkdir()
    sources = list((core / "src/main/java/org/enigmagrid/core").glob("*.java"))
    subprocess.run([str(args.jdk / "bin/javac.exe"), "-J-Xmx128m", "-d", str(output),
                    *map(str, sources), str(backend), str(core / "NativeUnavailableChecks.java")],
                   check=True, timeout=60)
    subprocess.run([str(args.jdk / "bin/java.exe"), "-Xmx128m", f"-Djava.library.path={native}",
                    "-cp", str(output), "org.enigmagrid.android.NativeUnavailableChecks"],
                   check=True, timeout=30)
