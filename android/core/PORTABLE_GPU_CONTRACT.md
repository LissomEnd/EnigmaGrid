# Portable GPU solver preparation

Status: experimental source only; not called by the official worker. Shader
compilation and host random-stream tests do not establish GPU receipt parity.

`PortableRandomTape` prepares canonical draws for independent 256-trajectory
cohorts. `portable_solver.comp` keeps mutation, complete 72-character decryption,
integer scoring, acceptance and best-state tracking on the GPU between chunks.
CPU workers must own different cohorts. Merge completed cohort winners by cost,
then canonical attempt index, exactly as `PortableSearchJob` does.

## Buffer contract

All arrays contain 32-bit integers with scalar `std430` array stride 4.

- Binding 0: ciphertext 72 integers, electrical tables 625 integers (including
  the unused header), then 456976 positive checksum-qualified quadgram integers.
- Binding 1: `((iteration * trajectories + trajectory) * 5) + field`, where
  fields are operation, a, b, value, cooling allowance. Iteration here is local
  to the dispatch; the tape producer retains the global cooling schedule.
- Binding 2: 86 integers per trajectory: current key 42, best key 42, current
  cost, best cost. Initialize the whole buffer before the first dispatch.
- Push constants: trajectories, chunk iterations, initialize, min pairs,
  max pairs, kind count, six event-kind slots; 48 bytes total.

Only the first dispatch uses initialize=1. Later chunks preserve resident state.
One 16-iteration chunk for eight cohorts transfers 655360 bytes (640 KiB) of
draws. A complete 4096-trajectory, 512-iteration unit transfers 40 MiB of draws;
the reference table is uploaded once per context. Do not allocate a full tape
per job on memory-constrained devices.

## Required host gates before activation

Validate every buffer length, index range, workgroup limit and scope before
dispatch. The shader assumes keys, permutations, event parameters and tape
values already validated. Positive reference costs 2357..10924 and the 20000
empty-side fallback fit signed 32-bit sums and preserve floor-division behavior.
Other tables require separate bounds/parity qualification.

Use persistent buffers, explicit transfer/compute/readback visibility and a
bounded fence wait. Never free or reuse buffers while commands may still access
them. Check cancellation, battery and thermal gates between bounded chunks.
Discard unfinished GPU cohort state after failure and recompute the same cohort
on CPU; do not create additional credited work or a second receipt.

Before production: compare full resident state and final receipts against the
independent reference across event kinds, pair ranges, chunk boundaries, ties,
failure and cancellation. Measure useful work per wall second with CPU and GPU
simultaneously, including tape generation and transfers. Unsupported devices
retain the qualified CPU path. No utilization or speedup claim is justified yet.

References: [Khronos memory layout](https://docs.vulkan.org/guide/latest/shader_memory_layout.html)
and [asynchronous compute](https://docs.vulkan.org/samples/latest/samples/performance/async_compute/README.html).
