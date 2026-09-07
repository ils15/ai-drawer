This directory contains the canonical Autodesk template snapshot used to freeze
the vendored `lib/fusionAddInUtils/` files in this repository.

Source:
- A freshly generated Autodesk Fusion Python add-in template (`NewAddIn`)

Last verified: 2026-09-06 against Autodesk Fusion **2705.1.11** (the
2026-09-03 release). All three Python files are byte-identical to the
installed macOS application's
`Contents/Libraries/Neutron/Python/DefaultAddIn/files/lib/fusionAddInUtils/`
template and to the live copies in this repository. Fusion 2704.1.53 and
2704.1.36 also contain the same files. No snapshot or hash update was needed.

[Autodesk release notes](https://help.autodesk.com/cloudhelp/ENU/Fusion-ReleaseNotes/files/FIC-REL-NOTES-INC.htm)

Policy:
- Do not hand-edit these snapshot files.
- Refresh them only by re-copying from a fresh Autodesk-generated template.
- `tests/test_autodesk_vendor_freeze.py` enforces both the snapshot hashes and
  the live vendored copies under `lib/fusionAddInUtils/`.
