"""Optional qualification memory evidence; no GPU, benchmark or production state."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
import portable_batch_qualification as p


class MemoryEvidence(unittest.TestCase):
    def test_null_errors_and_invalid_values_are_optional(self):
        values=iter([None,{},dict(working_set_bytes=float('nan'),private_commit_bytes=True),
                     dict(working_set_bytes=-1,private_commit_bytes=2**64)])
        evidence=p.QualificationMemoryEvidence(sampler=lambda:next(values))
        for _ in range(5):evidence.sample(force=True) # Last sampler call raises StopIteration.
        report=evidence.report()
        self.assertEqual(report['samples'],0)
        self.assertEqual(report['unavailable_samples'],5)
        self.assertIsNone(report['min_system_available_bytes'])
        self.assertTrue(all(value is None for value in report['maximum'].values()))
        json.dumps(report,allow_nan=False)

    def test_aggregation_and_throttled_checkpoint(self):
        at=[0.0]
        values=iter([dict(working_set_bytes=100,peak_working_set_bytes=120,private_commit_bytes=90,
                          peak_private_commit_bytes=130,system_available_bytes=1000),
                     dict(working_set_bytes=110,peak_working_set_bytes=150,private_commit_bytes=80,
                          peak_private_commit_bytes=140,system_available_bytes=800),
                     dict(working_set_bytes=70,system_available_bytes=900)])
        evidence=p.QualificationMemoryEvidence(sampler=lambda:next(values),clock=lambda:at[0])
        evidence.sample();at[0]=.1;evidence.sample()
        self.assertEqual(evidence.samples,1)
        at[0]=.3;evidence.sample();evidence.sample(force=True)
        report=evidence.report()
        self.assertEqual(report['samples'],3)
        self.assertEqual(report['latest']['working_set_bytes'],70)
        self.assertEqual(report['maximum']['working_set_bytes'],110)
        self.assertEqual(report['maximum']['peak_working_set_bytes'],150)
        self.assertEqual(report['maximum']['private_commit_bytes'],90)
        self.assertEqual(report['maximum']['peak_private_commit_bytes'],140)
        self.assertEqual(report['min_system_available_bytes'],800)
        self.assertNotIn('pid',json.dumps(report))

    def test_unsupported_platform_returns_none(self):
        with patch.object(p.os,'name','posix'):self.assertIsNone(p.windows_memory_sample())

    def test_sampler_failure_does_not_change_qualification(self):
        def failed():raise OSError('diagnostic API unavailable')
        clock=[0.0]
        evidence=p.QualificationMemoryEvidence(sampler=failed,clock=lambda:clock[0])
        def execute(blocks,checkpoint):
            checkpoint();clock[0]+={1:.2,4:.1,8:.08,16:.07}[blocks]
            return {'same':'canonical receipt'}
        report=p.qualify(execute,{'count':4096},'fixture','fixture',
                         checkpoint=evidence.sample,clock=lambda:clock[0])
        self.assertTrue(report['parity_passed'])
        self.assertEqual(report['selected_blocks'],16)
        self.assertGreater(evidence.report()['unavailable_samples'],0)


if __name__=='__main__':unittest.main()
