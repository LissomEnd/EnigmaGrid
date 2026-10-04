"""Run offline CPU/storage qualification on a disposable managed Linux emulator.

Requires an AVD named enigmagrid-cpu and a fresh GitHub-hosted runner.
Does not connect to user phones or enroll a contributor. No GPU claims.
"""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time


def main():
    if os.name != 'posix' or os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('This runner is restricted to managed Linux Actions')
    sdk = Path(os.environ['ANDROID_HOME'])
    api = int(os.environ['API_LEVEL'])
    if api not in (26, 35):
        raise ValueError('Supported qualification API levels: 26 and 35')
    adb = [str(sdk / 'platform-tools/adb'), '-s', 'emulator-5554']
    output = Path('android-emulator-results')
    output.mkdir(exist_ok=True)
    apk = Path('android/app/build/outputs/apk/lab/app-lab.apk')
    if not apk.is_file():
        raise FileNotFoundError(apk)
    command = [str(sdk / 'emulator/emulator'), '-avd', 'enigmagrid-cpu',
               '-port', '5554', '-no-window', '-no-audio', '-no-boot-anim',
               '-no-snapshot', '-wipe-data', '-gpu', 'swiftshader_indirect',
               '-accel', 'on', '-cores', '2', '-memory', '2048',
               '-camera-back', 'none', '-camera-front', 'none']
    record = dict(commit=os.environ.get('GITHUB_SHA'), api=api, abi='x86_64',
                  test='CPU receipts + Android Keystore + durable result queue',
                  physical_gpu_qualified=False, emulator_command=command)
    process = None
    def run(args, timeout=30, check=True):
        return subprocess.run(args, capture_output=True, text=True,
                              timeout=timeout, check=check)
    try:
        run([str(sdk / 'platform-tools/adb'), 'start-server'])
        with (output / 'emulator.log').open('w') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError('Emulator exited before boot')
                ready = run(adb + ['shell', 'getprop', 'sys.boot_completed'], timeout=10, check=False)
                if ready.returncode == 0 and ready.stdout.strip() == '1':
                    break
                time.sleep(2)
            else:
                raise TimeoutError('Emulator boot exceeded 300 seconds')
            actual_api = run(adb + ['shell', 'getprop', 'ro.build.version.sdk']).stdout.strip()
            actual_abi = run(adb + ['shell', 'getprop', 'ro.product.cpu.abi']).stdout.strip()
            if actual_api != str(api) or actual_abi != 'x86_64':
                raise RuntimeError('Unexpected emulator API/ABI')
            run(adb + ['install', '-r', str(apk)], timeout=120)
            test = run(adb + ['shell', 'am', 'instrument', '-w',
                       'org.enigmagrid.android.lab/org.enigmagrid.android.CpuCompatibilityQualification'],
                       timeout=180, check=False)
            text = test.stdout + test.stderr
            (output / 'instrumentation.txt').write_text(text, encoding='utf-8')
            expected = rf'INSTRUMENTATION_RESULT: result=PASS CPU_COMPATIBILITY receipts=[1-9][0-9]* sdk={api} abi=x86_64 keystore_and_durable_queue=passed'
            if test.returncode or not re.search(expected, text) or not re.search(r'INSTRUMENTATION_CODE: -1\s*$', text):
                raise RuntimeError('Missing explicit successful CPU qualification result')
            record['passed'] = True
    except BaseException as error:
        record.update(passed=False, error=f'{type(error).__name__}: {error}')
        raise
    finally:
        if process is not None:
            try:
                run(adb + ['emu', 'kill'], timeout=5, check=False)
            except (OSError, subprocess.SubprocessError):
                pass
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
        log_path = output / 'emulator.log'
        if log_path.exists():
            with log_path.open('rb') as source:
                source.seek(max(0, log_path.stat().st_size - 131072))
                tail = source.read()
            log_path.write_bytes(tail)
        (output / 'qualification.json').write_text(json.dumps(record, indent=2) + '\n')


if __name__ == '__main__':
    main()
