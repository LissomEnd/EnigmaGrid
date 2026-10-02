"""Reject unsafe native-array inputs before decrypting volunteer submissions."""
import copy
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"server"))
from validator import _validate_key, _letters

valid={"reflector":"B_THIN","greek":"BETA","moving_rotors":["I","II","III"],
       "rings":"AAAA","positions":"AAAA","plugboard":["AB","CD"]}
_validate_key(valid)
for field,values in {
    "rings":["", "AAA", "AAAAA", "AAAé", "aaaA", [0,0,0,0]],
    "positions":[None,"AAA[","AAA0"],
    "moving_rotors":[[],["I","I","II"],[{},"II","III"]],
    "plugboard":["AB",["AA"],["AB","AC"],["A["],["ABC"],[["A","B"]]],
    "reflector":[{},None],"greek":[[],1],
}.items():
    for value in values:
        key=copy.deepcopy(valid);key[field]=value
        try:_validate_key(key)
        except ValueError:pass
        else:raise AssertionError((field,value))
assert not _letters("É"*72,72)
assert not _letters("AAA[",4)
print("VALIDATOR_NATIVE_BOUNDS_OK")
