# Research qualification

The exploratory campaign is paused for scientific validation. Existing results
and contribution records are preserved. Connected clients can remain installed;
they will wait for eligible work. No replacement campaign is qualified yet.

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
