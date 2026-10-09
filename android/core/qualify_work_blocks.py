"""Cross-language block subdivision and legacy job-identity parity."""
import argparse
import json
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'solver/runtime/src'))
from search.work_block import unit_envelope
from search.crib_work import validate_envelope

p = argparse.ArgumentParser()
p.add_argument('--jdk', required=True)
a = p.parse_args()
block = dict(format='bounded_work_block_v2', block_id='block-test',
             engine='bounded_crib_v1', start_unit=4, end_unit=12,
             config=dict(requires=['cpu', 'bounded_crib_v1'], program=dict(
                 ciphertext='BDZGO', hypotheses=[dict(text='BD', legal_clean_offsets=[0])],
                 chunk=3, ordinal_base=2, candidate_limit=3)))

def java(value):
    if isinstance(value, dict):
        return 'object(' + ','.join(java(x) for pair in value.items() for x in pair) + ')'
    if isinstance(value, list):
        return 'Arrays.asList(' + ','.join(map(java, value)) + ')'
    return json.dumps(value)

source = '''import java.util.*;import org.enigmagrid.core.*;import static org.enigmagrid.core.Canonical.*;
public class BlockChecks {
static void reject(Runnable r){try{r.run();}catch(IllegalArgumentException expected){return;}throw new AssertionError("Accepted invalid block");}
public static void main(String[] args){Map<String,Object> block=BLOCK;
WorkBlock.validate(block);reject(()->WorkEnvelope.validate(block));
for(long n=4;n<12;n++)System.out.println(json(WorkEnvelope.validate(WorkBlock.unitEnvelope(block,n))));
reject(()->WorkBlock.unitEnvelope(block,3));reject(()->WorkBlock.unitEnvelope(block,12));
for(Object bad:Arrays.asList(true,4.0,-1L,Long.MAX_VALUE)){Map<String,Object> b=new LinkedHashMap<>(block);b.put("start_unit",bad);reject(()->WorkBlock.validate(b));}
for(Object bad:Arrays.asList(1000005L,Long.MIN_VALUE,4L)){Map<String,Object> b=new LinkedHashMap<>(block);b.put("end_unit",bad);reject(()->WorkBlock.validate(b));}
Map<String,Object> b=new LinkedHashMap<>(block);b.put("block_id","../outside");reject(()->WorkBlock.validate(b));
Map<String,Object> child=WorkBlock.unitEnvelope(block,4);((Map)((Map)child.get("config")).get("program")).put("chunk",1);
if(!json(block).equals(json(BLOCK)))throw new AssertionError("Shared mutable config");
Map<String,Object> invalid=WorkBlock.unitEnvelope(block,4);
invalid.put("format",WorkBlock.FORMAT);invalid.put("block_id","invalid-middle");invalid.put("start_unit",0);invalid.put("end_unit",3);
Map<String,Object> program=(Map<String,Object>)((Map)invalid.get("config")).get("program");
program.put("ordinal_base",0);program.put("hypotheses",Arrays.asList(object("text","A","legal_clean_offsets",Arrays.asList(0)),object("text","BB","legal_clean_offsets",Arrays.asList(4)),object("text","C","legal_clean_offsets",Arrays.asList(0))));
reject(()->WorkBlock.validate(invalid));
}}
'''.replace('BLOCK', java(block))
with tempfile.TemporaryDirectory(prefix='enigma-blocks-') as folder:
    d = pathlib.Path(folder)
    f = d / 'BlockChecks.java'
    f.write_text(source, encoding='utf-8')
    binaries = pathlib.Path(a.jdk) / 'bin'
    sources = list((root / 'android/core/src/main/java').rglob('*.java'))
    subprocess.run([str(binaries / 'javac.exe'), '-encoding', 'UTF-8', '-d', str(d),
                    *map(str, sources), str(f)], check=True)
    result = subprocess.run([str(binaries / 'java.exe'), '-cp', str(d), 'BlockChecks'],
                            check=True, capture_output=True, text=True)
    actual = [json.loads(line) for line in result.stdout.splitlines()]
    assert actual == [validate_envelope(unit_envelope(block, n)) for n in range(4, 12)]
print('PASS Android/Python block subdivision parity, strict ranges, legacy rejection and isolated unit config')
