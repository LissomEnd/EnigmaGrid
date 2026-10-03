# Research qualification

The existing exploratory campaign remains active while replacement methods are
evaluated separately. Existing results and contribution records are preserved.
No replacement campaign is qualified yet. Research qualification must not
interrupt the current campaign before a tested replacement is ready to take over.
An additional experimental campaign is being prepared alongside the existing
campaign. It is not a replacement and has no demonstrated recovery advantage.
The constrained client supports bounded, indexed CPU jobs and preserves budget
cutoffs as unknown results. Matching computations verify execution, not a
historical decryption or exhaustive elimination outside the stated hypothesis.

Indexed jobs avoid repeating their own mechanical-core sequence within each
crib hypothesis. Different hypotheses may examine the same mechanical settings;
this is not a claim that nobody else has tested those keys. Duration estimates
depend on available volunteers and include separate verification work.

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
runs at most eight offline jobs or 30 seconds by default, checked between
mechanical cores. One bounded core and checkpoint I/O may exceed the time limit.
An expired in-flight job saves no receipt and is retried on the next invocation.
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

### Prior-work overlap audit

The HELUT catalog at commit `d90da14950a692331917a081dc527e1e5b3a2eea`
was compared with the 112 proposed clean placements. 67 have identical or
containing/contained constraints; this is not proof those settings were executed.
Its [VIII-fast log](https://github.com/Digital-Defiance/HELUT/blob/d90da14950a692331917a081dc527e1e5b3a2eea/logs/campaign-catalog-rings-viii-fast.log)
explicitly limits that run to 42 of 336 rotor orders.

`scripts/audit_crib_overlap.py` compares an external catalog with a proposal,
checks ciphertext equality, records file hashes, and distinguishes the direction
of constraint implication. Zero exclusions are authorized by this comparison.
Mapping matching placements to completed, independently checked key-domain
receipts remains necessary before removing work. No external source code was
executed and no third-party claim of a solution is adopted.

The optional `--execution-log` maps exact text/offset pairs to reported log rows,
retaining line numbers and a source hash. The pinned VIII-fast log maps to 22 of
our 112 placements. Its middle ring is fixed as well as its restricted rotor
orders. No key-domain exclusions follow: reported execution and heuristic
rejection do not establish an independently verified exhaustive negative.

### Experimental job safety

The offline crib executor validates the alphabet, placement, cable count, unique
core indices and fixed maximum search budgets before doing any search. When a
job includes an identity hash, altered work is rejected. A caller can provide a
checkpoint callback between mechanical cores to enforce pause or cancellation;
an exception stops execution without returning a completed receipt. This is not
yet wired into the volunteer client. Cancellation cannot interrupt a core already
being evaluated, whose search is bounded by the validated limits.

`worker/research_executor.py` provides an offline client adapter for testing those
callbacks with pause, stop and CPU duty controls. It uses one computational thread
and interprets the CPU percentage conservatively as a fraction of one core.
Pauses and cooldown waits check controls every 50 ms; an active bounded core must
finish before controls are checked. GPU execution is unsupported. The production
worker does not advertise or route this engine, and coordinator/validator
integration remains a separate qualification gate.

`search/research_validation.py` recomputes an experimental job and compares its
entire JSON receipt, rejecting altered scope, counters, candidates and completion
claims. Verification can be cancelled through the same checkpoint mechanism.
Agreement on a budget cutoff stays `unknown_budget`, never a complete negative.
This offline check issues no credit and reuses the search implementation: it is
not independent validation of the algorithm, and is not a production endpoint.

### Capacity gate

The horizon planner now includes at least two executions per job (search and
separate recomputation), and reports scheduled coverage separately from recovery
probability. At the pilot's approximately 250.73 core-hypothesis pairs/second,
one device at 10% duty for 90 days could schedule about 97.5 million distinct
pairs, at most 0.000210% of the 46.5 trillion-pair proposal. This is an illustrative
upper bound: cutoffs, retries, overhead and heterogeneous devices reduce coverage.
The pilot rate is not a measured fleet throughput or a reliable completion ETA.
Broad uniform scheduling is therefore not yet a justified replacement campaign;
stronger hypothesis evidence, domain reduction or substantial acceleration is
needed, alongside successful recovery benchmarks. The existing campaign stays
active while this research remains isolated.

### Historical key-network constraint

The [target's indicator analysis](https://enigma.hoerenberg.com/index.php?cat=Unbroken&page=P1030680)
tentatively assigns it to Thetis and describes unsuccessful Potsdam attempts.
`tests/test_indicator_replay.py` reproduces those reported computations with the
original VCCH rings, plus the separate P1030690 indicator example documented in
the [Kenngruppen explanation](https://enigma.hoerenberg.com/index.php?cat=The+U534+messages&page=The+Kenngruppen+System).
Using original written positions with the solved fixtures' AACU rings is invalid.
These checks support the transcription and simulator convention, not a target
decrypt. The unsuccessful output is not a plaintext crib. Neither the nearby
solved messages' daily key nor the surviving indicator notes justify restricting
the target to Potsdam settings; recovering Thetis key material would require
additional historical evidence.

`tests/test_crib_exhaustive.py` adds an independent enumeration oracle for small
domains: all zero/one-cable plugboards across two supplied mechanical cores,
with clean, substitution and omission models. All 24 cases match the solver's
complete candidate sets. The oracle shares the reference Enigma simulator but
does not use CSP propagation or board completion. This checks finite low-cable
domains; it is not evidence of practical full-space ten-cable recovery.

The server validator supports an explicit `allow_experimental=True` argument
for isolated one-job lease tests. It binds the receipt to the job in the lease
configuration and recomputes it. The production HTTP path does not opt in and
continues to reject this engine. No experimental campaign is scheduled by this
change. Production integration still requires bounded asynchronous verification,
client capability negotiation and scientific qualification.

### Additional daily-key control

The historical suite now includes [P1030713](https://enigma.hoerenberg.com/index.php?cat=The+U534+messages&page=P1030713), solved by Enigma@Home in 2013. Its May 2, 1945 key is distinct from the previous controls. The raw published decryption, including apparent garbles, reproduces exactly with both simulators. All 24 bounded cases across four messages and three daily keys pass. These remain known-crib tests with the true mechanical core among 128 supplied alternatives, not full unknown-key recovery. This fixture must not be used to train a replacement language model and then reported as a held-out success. Earlier 18-case reports above describe the earlier suite.

### Reproducing the known-core scoring diagnostic

Run `python scripts/benchmark_plugboard.py --output result.json`. This uses the
four published fixture messages, supplies the correct mechanical core, and
searches only the plugboard. It is intentionally easier than blind recovery.
The fixed seed, sixteen restarts, neighborhood invariants and reference replay
make failures inspectable. It uses approximately 10% duty on one thread.

The generic quadgram run recovered 0/4 messages. On three of the four controls,
its best incorrect candidate even outranked the historical truth. This is a
ranking failure for that objective, not just failure to find a key. It does not
test the production event-balanced objective.

Optional `--trigrams PATH` accepts locally supplied uppercase trigram/count data;
`--bigrams PATH` additionally enables IC/bigram/trigram stages.
`--variable-cables` adds removal/connection moves and varies initial cable count.
These are diagnostic variants, not implementations of the complete published
Ostwald/Weierud attack. Different variants use different evaluation counts, so
compare recovery and scope, not absolute costs or nominal restart counts alone.
The report records external table hashes. No external data is downloaded.

Local experiments with the [Sullivan/Weierud 1941 military frequencies](https://cryptocellar.org/bgac/key-of-e.html)
recovered 0/4 with each tested variant. They improved some ranking comparisons,
but a wider candidate search found additional false texts outranking truth.
Those tables are not bundled or relicensed here. The controls remain excluded
from language-model training. These negative results do not prove impossibility;
they prevent promoting an unqualified method merely because its score improves.
