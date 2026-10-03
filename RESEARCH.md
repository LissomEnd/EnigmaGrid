# Research qualification

The existing exploratory campaign remains active while replacement methods are
evaluated separately. Existing results and contribution records are preserved.
No replacement campaign is qualified yet. Research qualification must not
interrupt the current campaign before a tested replacement is ready to take over.
Any replacement also requires the owner's explicit confirmation, even after
technical qualification. No automatic switchover is authorized.

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

`scripts/prepare_research_campaign.py --output proposal.json` prepares an inert
proposal with attributed crib windows, legal offsets, explicit work bounds,
scope sizing and activation gates. It neither reads nor changes the live
database and is not accepted as a production manifest. Five source windows
yield 112 legal clean placements, spanning about 46.5 trillion core/hypothesis
pairs if all canonical settings are explored. A full CPU-only sweep is not a
practical allocation at measured prototype throughput; no such sweep is queued.
The proposal includes a capped, deterministic CPU pilot: 112 jobs of 128 sampled
mechanical cores each (14,336 core/hypothesis pairs). Job IDs and sampled cores
are reproducible. It has not been executed on the target. This small pilot is
for runtime and candidate-rate measurement; it cannot exclude the full domain.
`search.crib_pilot` provides offline generation and execution, tested against a
historical control. The proposal still requires overlap review against prior
work, production integration and explicit user approval. It is not a replacement
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
