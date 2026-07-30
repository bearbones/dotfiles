## Summary

Cosmetic replacement of `BOOST_*` test macros with their `RBX_*` equivalents in `{BATCH_ID}`.

**Compiled output is identical.** `Client/Base.UnitTest.Lib/include/rbx/test/RBXTest.hpp` defines every `BOOST_*` macro as a direct `#define` alias to the corresponding `RBX_*` macro, so this change removes source-level indirection only.

Files changed: `{FILE_COUNT}` (all in test directories)

## Why

We are retiring the `BOOST_` compatibility shim in `RBXTest.hpp`. Once all usages are replaced the shim file can be deleted, removing the last dependency on Boost test naming conventions from our test codebase.

## Verification

- [ ] `gobot uv run Tools/Scripts/boost_to_rbx.py --check {FILES}` exits 0 (no remaining BOOST_ macros)
- [ ] No changes to non-test files
- [ ] No changes to `Client/Base.UnitTest.Lib/`
- [ ] CI passes (no functional change expected)

## How to Review

This is a pure rename. The easiest review is to verify that every changed line follows one of these patterns:
- `BOOST_FOO(` → `RBX_FOO(`
- `BOOST_FOO_BAR(` → `RBX_FOO_BAR(` (or `RBX_FOO_BAZ(` for the few with different targets — see `RBXTest.hpp`)

The script that generated this PR: `Tools/Scripts/boost_to_rbx.py`
