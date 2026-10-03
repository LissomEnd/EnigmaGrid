# Third-party notices

## German quadgram frequency data

`solver/runtime/data/language/german_quadgrams.txt` was copied unchanged from
[Vladimir Cicovic's EnigmaM4Breaker](https://github.com/vladimir-cicovic/EnigmaM4Breaker),
commit `d238bb0fa8a021d0c40421e11643eaeb131b612d`, path
`data/german_quadgrams.txt`. Its SHA-256 is
`39c9341b5079b739fdae1c7c98bcadae106341611ba2635ffd680e1a45a7776b`.

The upstream README declares GNU GPL v3. The frequency data is not relicensed
under this project's MIT license. A copy of GPL v3 is included alongside it as
`COPYING.GPL-3.0.txt`. EnigmaGrid ships the human-readable frequency table, not
just a compiled scoring table. No upstream CUDA executable is bundled.

## Runtime dependencies

Windows packages include Python, NumPy, Numba, llvmlite, cryptography, PyOpenCL,
Pillow, pystray and their dependencies. These components retain their respective
licenses. Their versions are pinned by the requirements files. Source and
upstream license references are available from each package's distribution
metadata.

The Windows package includes `LICENSES.txt` with distribution metadata and
license texts collected from the exact build environment, plus Python's license.
The unmodified pystray component is LGPL v3; its source is available at
https://github.com/moses-palmer/pystray/tree/v0.19.5 and from its PyPI source
distribution. You can replace it and rebuild the application using
`scripts/Build-WindowsStandalone.ps1`. No restriction is imposed on reverse
engineering for debugging modifications to LGPL components.

EnigmaGrid's original source is covered by the root MIT license. Historical
rotor wiring and ciphertext are research inputs; a search result is not a claim
of authorship of the historical message.
