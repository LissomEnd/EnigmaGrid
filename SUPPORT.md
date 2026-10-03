# Help and troubleshooting

[Open an issue](https://github.com/LissomEnd/EnigmaGrid/issues/new/choose) for a
bug, installation question, hardware compatibility problem or feature request.
A GitHub account is needed to submit an issue. Reports are public. This is a
volunteer-maintained project; response times are not guaranteed.

Include the app version, Windows version, steps to reproduce, expected and
actual behavior, and CPU/GPU model and driver version when relevant. A short,
redacted error excerpt is more useful than an entire log. Never post dashboard
tokens, device credentials, private addresses, account paths or personal files.
Use [private security reporting](https://github.com/LissomEnd/EnigmaGrid/security/advisories/new)
for vulnerabilities or exposed secrets.

## The dashboard says 0% or my name is not on the leaderboard

Submitted work initially appears under **Awaiting validation**. Final progress
and credit require matching separate computations from another contributor or
the server's spare-capacity verifier. If the server is busy and no other
contributor can reproduce the work, pending work grows while verified progress
can remain zero. A public name appears only after verified credit, and only
if public credit was enabled. Do not create extra identities to self-validate.

## My GPU is unavailable

The Windows x64 client uses OpenCL, not CUDA. A compatible driver and a passing
local CPU/GPU equivalence check are required. CPU-only contribution still
works. AMD integrated graphics and Intel Iris Plus have been physically tested;
other vendors and drivers are not guaranteed. Report the model and driver
version if the check fails; do not disable the correctness check.

## Resource use differs from the slider percentage

CPU percentages set a thread budget. GPU percentages set a work/rest budget.
Neither promises an exact Task Manager reading. New limits apply at the next
job. Pause takes effect at a search checkpoint; safe stop finishes the current
job. Closing the window leaves the tray application running.

## Windows reports an unknown publisher

The executables are not Authenticode-signed. Download only from the official
release page and review its checksums, provenance and known limitations before
deciding whether to install. The signed update manifest protects update
integrity; it is not a Windows publisher certificate or a security audit.

## The worker restarts or reports a connection error

Use release 0.4.1 or later: 0.4.0 could restart after a temporary Windows lock on
its status file. Network interruptions are retried and abandoned leases are
reissued. If a current release repeatedly fails, open a bug report with a
redacted error excerpt and your app version.
