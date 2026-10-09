"""Isolated transition gate test. No production DB or activation."""
import sqlite3,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from c4_autoarm import check_db,PRE,DONE,C4
class GateTest(unittest.TestCase):
 def setUp(self):
  c=self.c=sqlite3.connect(':memory:')
  c.execute('create table campaigns(id text,status text)')
  c.execute('create table segments(id text,campaign_id text,next_unit integer,end_unit integer)')
  c.execute('create table validations(segment_id text,status text)')
  c.execute('create table submissions(segment_id text,status text)')
  c.execute('create table work_blocks(id text,segment_id text,status text)')
  c.execute('create table leases(segment_id text,status text)')
  c.execute('create table requeue(segment_id text)')
  c.execute('create table block_receipts(block_id text,promoted_at real,verification_status text)')
  for x in (*PRE,*DONE):c.execute('insert into campaigns values(?,?)',(x,'complete'))
  c.execute('insert into campaigns values(?,?)',(C4,'prepared'))
  for i,x in enumerate(PRE):c.execute('insert into segments values(?,?,?,?)',(str(i),x,10,10))
 def gate(self):return check_db(self.c)[0]
 def test_ready(self):self.assertIsNone(self.gate())
 def test_running(self):
  self.c.execute('update campaigns set status=? where id=?',('running',PRE[0]))
  self.assertIn('C3-still-running',self.gate())
 def test_unassigned(self):
  self.c.execute('update segments set next_unit=0 where id=?',('0',))
  self.assertIn('C3-index-unassigned',self.gate())
 def test_validations(self):
  self.c.execute('insert into validations values(?,?)',('0','pending'))
  self.assertIn('C3-validations-outstanding',self.gate())
 def test_accepted_trusted_is_final_credit(self):
  self.c.execute('insert into validations values(?,?)',('0','accepted_trusted'))
  self.assertIsNone(self.gate())
 def test_manual_review_blocks(self):
  self.c.execute('insert into validations values(?,?)',('0','manual_review'))
  self.assertIn('C3-validations-outstanding',self.gate())
 def test_pending(self):
  self.c.execute('insert into submissions values(?,?)',('0','pending'))
  self.assertIn('C3-submissions-pending',self.gate())
 def test_reserved(self):
  self.c.execute('insert into work_blocks values(?,?,?)',('block_0','0','reserved'))
  self.assertIn('C3-blocks-reserved',self.gate())
 def test_lease(self):
  self.c.execute('insert into leases values(?,?)',('0','leased'))
  self.assertIn('C3-leases-active',self.gate())
 def test_requeue(self):
  self.c.execute('insert into requeue values(?)',('0',))
  self.assertIn('C3-requeue-pending',self.gate())
 def test_unpromoted(self):
  self.c.execute('insert into work_blocks values(?,?,?)',('block_1','0','complete'))
  self.c.execute('insert into block_receipts values(?,?,?)',('block_1',None,'pending'))
  self.assertIn('C3-unpromoted-receipts',self.gate())
 def test_idempotent(self):
  self.c.execute('update campaigns set status=? where id=?',('running',C4))
  self.assertEqual(self.gate(),'already-running')
if __name__=='__main__':unittest.main()
