"""Inspect native ABI and 16 KiB ELF/ZIP alignment; does not test GPU drivers."""
import argparse
import struct
import zipfile
from pathlib import Path


def inspect(apk):
    expected = {'arm64-v8a': (2, 183), 'armeabi-v7a': (1, 40), 'x86_64': (2, 62)}
    seen = set()
    with zipfile.ZipFile(apk) as archive, open(apk, 'rb') as raw:
        for item in archive.infolist():
            parts = item.filename.split('/')
            if len(parts) != 3 or parts[0] != 'lib' or not parts[2].endswith('.so'):
                continue
            abi = parts[1]
            data = archive.read(item)
            assert data[:4] == b'\x7fELF' and data[5] == 1, item.filename
            elf_class = data[4]
            machine = struct.unpack_from('<H', data, 18)[0]
            assert expected.get(abi) == (elf_class, machine), item.filename
            if elf_class == 2:
                offset = struct.unpack_from('<Q', data, 32)[0]
                size, count = struct.unpack_from('<HH', data, 54)
                fmt = '<IIQQQQQQ'
            else:
                offset = struct.unpack_from('<I', data, 28)[0]
                size, count = struct.unpack_from('<HH', data, 42)
                fmt = '<IIIIIIII'
            assert size >= struct.calcsize(fmt) and count > 0, item.filename
            loads = 0
            for i in range(count):
                header = struct.unpack_from(fmt, data, offset + i * size)
                if header[0] != 1:
                    continue
                loads += 1
                file_offset, address = header[2:4] if elf_class == 2 else header[1:3]
                assert header[7] >= 16384 and (address - file_offset) % 16384 == 0, item.filename
            assert loads, item.filename
            # Stored libraries can be mapped directly from the APK.
            if item.compress_type == zipfile.ZIP_STORED:
                raw.seek(item.header_offset)
                local = raw.read(30)
                assert local[:4] == b'PK\x03\x04', item.filename
                name_size, extra_size = struct.unpack_from('<HH', local, 26)
                assert (item.header_offset + 30 + name_size + extra_size) % 16384 == 0, item.filename
            if parts[2] == 'libenigmagrid_gpu.so':
                seen.add(abi)
            print('PASS native layout:', item.filename)
    assert seen == set(expected), f'Missing GPU ABIs: {set(expected)-seen}'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('apk', type=Path)
    inspect(parser.parse_args().apk)
