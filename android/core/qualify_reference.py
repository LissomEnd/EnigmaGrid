"""Compare Java CPU primitive with the existing independent Python reference.

Uses all moving-rotor orders, both Greek rotors and reflectors, randomized rings,
positions and plugboards. This qualifies the cipher primitive, not a search engine.
"""
import argparse
import itertools
import pathlib
import random
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'solver/runtime/src'))
from reference.enigma_m4 import crypt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--jdk', type=pathlib.Path, required=True)
    args = parser.parse_args()
    rng = random.Random(1030680)
    alpha = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    rows, expected = [], []
    for moving in itertools.permutations(('I','II','III','IV','V','VI','VII','VIII'), 3):
        for greek, reflector in itertools.product(('Beta','Gamma'), ('Bthin','Cthin')):
            positions = ''.join(rng.choices(alpha, k=4))
            rings = ''.join(rng.choices(alpha, k=4))
            contacts = list(alpha); rng.shuffle(contacts)
            count = rng.randrange(14)
            pairs = [''.join(contacts[2*i:2*i+2]) for i in range(count)]
            text = ''.join(rng.choices(alpha, k=128))
            fields = [text, reflector, greek, ','.join(moving), positions, rings, ','.join(pairs)]
            rows.append('|'.join(fields))
            expected.append(crypt(text, reflector, greek, moving, positions, rings, pairs))
    # Explicit double-step boundary and nonzero rings.
    rows.append('A'*100+'|Bthin|Beta|I,II,III|AADV|BCDE|AZ,BY')
    expected.append(crypt('A'*100,'Bthin','Beta',('I','II','III'),'AADV','BCDE',['AZ','BY']))
    rows += ['ABC|Bthin|Beta|I,II,III|AAAA|AAAA|AB,AC',
             'ABC|Bthin|Beta|I,I,III|AAAA|AAAA|',
             'abc|Bthin|Beta|I,II,III|AAAA|AAAA|']
    expected += ['INVALID']*3
    with tempfile.TemporaryDirectory(prefix='enigmagrid-java-') as tmp:
        subprocess.run([str(args.jdk/'bin/javac.exe'), '-d', tmp,
            str(ROOT/'android/core/src/main/java/org/enigmagrid/core/EnigmaM4.java'),
            str(ROOT/'android/core/ReferenceCli.java')], check=True)
        proc = subprocess.run([str(args.jdk/'bin/java.exe'), '-cp', tmp, 'ReferenceCli'],
            input='\n'.join(rows)+'\n', text=True, capture_output=True, check=True)
        actual = proc.stdout.splitlines()
        if actual != expected:
            for i, (got, want) in enumerate(itertools.zip_longest(actual, expected)):
                if got != want: raise AssertionError(f'Case {i}: {got!r} != {want!r}')
    print(f'PASS: {len(rows)} cross-language cipher and rejection cases')


if __name__ == '__main__':
    main()
