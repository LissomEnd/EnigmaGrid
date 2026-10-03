# Research qualification

The existing exploratory campaign remains active while replacement methods are
evaluated separately. Existing results and contribution records are preserved.
No replacement campaign is qualified yet. Research qualification must not
interrupt the current campaign before a tested replacement is ready to take over.
The owner has authorized a replacement only after testing demonstrates a useful
advantage and a safe, reversible transition is prepared. The running campaign
continues until those conditions are met.

Two separate research engines now support evaluation:

- `bounded_crib_v1` searches an explicitly supplied finite mechanical domain
  with unknown plugboard, exact cable count and standard M4 stepping. Clean,
  one-substitution and one-omission models are distinct. An omitted character
  consumes a machine step. A budget cutoff is UNKNOWN, never an exclusion.
- `portable_standard` is a CPU-only no-event heuristic baseline, with canonical
  Greek/left rings and cable-count-preserving rewiring. It is not a production
  engine and does not alter the released v1 trajectories.

Run `python tests/test_bounded_crib.py` for synthetic controls with hidden
plugboards, long cribs, two different mechanical configurations and all three
error models. This is constrained recovery, not a fully blind key search.

Run `python scripts/benchmark_research.py --output pilot.json` for smaller cribs,
negative controls and bounded no-crib comparisons. The pilot uses one CPU
thread. Equal trajectory counts are not equal execution time. Neither short
tests nor replay of a supplied key establish target-solving ability.

Observed pilot results on 2026-10-03: 0/12 blind trials recovered the plaintext
(six per heuristic); 6/6 constrained trials recovered the key in a domain of
32 cores using 16-, 24- or 32-letter cribs. The 16-letter cases retained ten
and six candidates, respectively. Ten random negative controls deliberately
avoiding self-encryption conflicts produced zero candidates and no budget
cutoffs. These small, synthetic samples are not estimates of real-target
success probability. The constrained domain includes the true mechanical
core; its identity and plugboard are not passed to the solver.

Further controls on 2026-10-03: `tests/test_historical_recovery.py` recovered
the historical key in all twelve bounded cases from P1030683 and P1030684,
using 24/32-letter cribs, 128 supplied cores, and clean/injected-error models.
Both messages share a daily key, so these are not twelve independent historical
keys. Full source plaintext replay agrees in two local implementations.

`scripts/benchmark_equal_time.py --seconds 2 --output comparison.json` runs
twelve blind trials on those historical prefixes with the same wall-time
budget per method (one bounded batch can overshoot). The observed result was
zero recoveries. This short benchmark cannot establish general ineffectiveness.

An extended comparison at ten seconds per trial (six trials per heuristic,
two historical prefixes) also yielded zero exact plaintext recoveries for both
methods. Combined with the small target pilot, this does not demonstrate an
advantage sufficient to replace the running campaign. Decision: keep v1 active;
retain the new engine as a research prototype. No production transition occurred.

`scripts/prepare_research_campaign.py --output proposal.json` prepares an inert
proposal with attributed crib windows, legal offsets, explicit work bounds,
scope sizing and activation gates. It neither reads nor changes the live
database and is not accepted as a production manifest. Five source windows
yield 112 legal clean placements, spanning about 46.5 trillion core/hypothesis
pairs if all canonical settings are explored. A full CPU-only sweep is not a
practical allocation at measured prototype throughput; no such sweep is queued.
The proposal includes a capped, deterministic CPU pilot: 112 jobs of 128 sampled
mechanical cores each (14,336 core/hypothesis pairs). Job IDs and sampled cores
are reproducible. An isolated target run on 2026-10-03 completed all 112 jobs
in 94.29 seconds, with zero candidates and no budget cutoffs. This small pilot is
for runtime and candidate-rate measurement; it cannot exclude the full domain.
`search.crib_pilot` provides offline generation and execution, tested against a
historical control. The proposal still requires overlap review against prior
work, production integration and evidence supporting the conditional switch. It is not a replacement
Windows release and cannot yet be assigned to existing volunteer clients.

The current campaign's equal allocation across 0–3, 4–10 and 11–13 cables,
17 event positions and mixed event models is exploratory, not an empirically
validated allocation. Its 75,000 units do not exhaust the Enigma keyspace.

Before a replacement receives volunteer compute it must have a versioned
manifest, source-backed hypotheses, held-out historical controls, bounded
resource use, independent replay, reproducible scope receipts, and measured
recovery/false-positive behavior. Deployment also requires worker/validator
compatibility tests. These research functions are deliberately not routed by
the public worker. No new Windows release is implied by their presence.

Background: [target record and indicator analysis](https://enigma.hoerenberg.com/index.php?cat=Unbroken&page=P1030680),
[prior HELUT work](https://github.com/Digital-Defiance/HELUT/blob/main/writeup.md),
[Krah's M4 project](https://www.bytereef.org/m4_project.html).
Published negatives must be matched to their exact crib, model and key domain
before excluding duplicate work. No decryption of P1030680 is claimed.

### Candidate quality and prototype improvements

A read-only audit on 2026-10-03 independently replayed 3,248 stored candidate
keys and event descriptions with the pure Python rotor implementation: no
plaintext discrepancies were found. The highest-ranked texts inspected did not
establish a coherent historical message. Replay agreement validates computation,
not the research hypothesis or a decryption claim.

`scripts/calibrate_language.py --output calibration.json` compares the current
German quadgram model with the two historical 72-letter controls and 1,000
deterministic letter shuffles per control. An optional `--candidate-texts` accepts
a JSON list of plaintext strings; it does not access production state. In a
later snapshot of 3,304 optimized candidates, 1,248 scored at least as highly as
P1030683 and 2,248 as P1030684 under full-message quadgrams. None of the 1,000
shuffles per control did so. This illustrates why random-shuffle performance
cannot calibrate false positives after an optimization search. These two
controls are not a representative corpus and must not become training data for
a replacement score. Stronger, independent naval-message controls remain needed.

The constrained prototype now computes electrical permutations only inside the
crib window while advancing all preceding mechanical steps. Differential tests
cover random ring/start settings, double-notch rotors, nonzero offsets and
clean/substitution/omission receipts. Experimental no-event search results now
include full keys for independent replay; no plaintext-only result needs to be
trusted. These changes do not modify the deployed event engine or activate a
replacement campaign.

Repeating the same 112 target pilot jobs after this optimization took 57.18
seconds locally versus 94.29 seconds in the earlier run (about 39% less elapsed
time; machine load was not controlled). All receipt fields, including scope
hashes, node counts and completion status, matched the previous run exactly.
Both runs found zero candidates. This improves throughput, not demonstrated
recovery probability, and does not make the full domain practical.

A third held-out control is now sourced from the M4 Project's
[U264 break](https://www.bytereef.org/m4-project-first-break.html), using its
raw 232-letter log decryption rather than the edited interpretation. It has a
different daily key from the two U534 controls. This extends historical tests
without teaching the language model the answers. All 18 bounded historical
cases passed, including the six new cases; full replay also matched in two
implementations. The U264 prefix scores -5.7033, exceeded by three of the same
3,304 optimized candidates. This remains a diagnostic comparison, not an
estimated false-positive probability or a full unknown-key recovery benchmark.

### A durable research program, not repeated campaign replacement

`search.research_program` prepares a 90-day planning horizon. Work is indexed
and reproducible: round-robin crib/offset hypotheses, batches of 128 cores, and
a bijective modular permutation within each mechanical domain. Extending the
calendar estimate does not change previously defined jobs. Core ranges never
wrap and do not repeat within a hypothesis. This does not establish non-overlap
with the earlier random pilot or third-party searches.

`scripts/run_research_program.py --proposal proposal.json --state-dir PRIVATE_DIR`
runs at most eight offline jobs or 30 seconds by default, checked between jobs.
It stores hashed receipts and an atomic checkpoint, detects a changed proposal
or corrupt stored receipt, and resumes after the last saved job. A concurrent
runner is refused. After a crash a stale lock needs manual inspection; no
automatic lock stealing occurs. An interrupted in-flight job may be repeated;
saved receipts are reused. Unknown-budget results remain explicitly unknown.

The horizon is a capacity estimate, not a commitment to spend 90 days on an
unqualified hypothesis. Weekly review covers independent recovery, candidate
quality, resources and overlap with prior work. Regression or invalidated
hypotheses stop experimental work; the existing volunteer campaign remains
running. Production promotion still needs demonstrated research benefit and
tested worker/validator compatibility. This runner has no production access.
