# Python 3.12 integration

This integration was reconciled with the current default branch on 2026-11-12.
The immutable Python 3.9 / AiiDA 2.6.3 releases remain separate and unchanged.
Its implementation sources are:

| Source | Revision | Role |
| --- | --- | --- |
| `master` | `3f07576` | Current upstream, including all Fabio changes through #152 |
| `fix/upload-diagnostics` (#127) | `b55ad0e` | Authoritative simulation import/export implementation and diagnostics |
| `fix-package-discovery-py312` (#114) | `2b91a2c` | Package discovery and ipywidgets startup fixes |

The diagnostic branch already contains the simulation stack through #126.
The integration retains that implementation, including single-root archive
splitting, scalar UUIDs, provenance/origin handling, incomplete-export recovery,
molecule lookup and per-upload diagnostic reports. No transport tuning is added.

Merge conflicts preserve conditional notebook imports, separate project and
experiment selectors, measurement-log helpers, synchronisation, current pyBIS
selection, process-template ordering, observable dataset names, the empty-action
guard and instrument locking. Log paths remain anchored to the app. The packaging branch's safe accordion update
order is integrated without reverting those behaviors.

## Runtime policy

Python >=3.12 and AiiDA >=2.8 are the explicitly requested support floors.
This closes the earlier Python 3.9 compatibility window for this integration;
it is a support-policy decision, not a claim of a newly reproduced failure on
every older version. The pre-existing AiiDA <3 bound is retained. No unrelated
dependency pins are changed or upgraded.

The `aiidalab-eln>=0.1.4` requirement comes from #114: that release introduced the
openBIS connector absent from 0.1.3. Correcting `package` to `packages = find:`
addresses the documented editable-install `aiida_openbis` import failure.
Earlier tests used Python 3.12.11 / AiiDA 2.8.0. The reconciled source passes
308 offline tests on Python 3.12.11 / AiiDA 2.9.4 / official widgets-base 3.0.1,
including a separate run against the declared official pyBIS 7.0.0rc6 source
artifact. These are isolated source tests; they do not establish that the
active installation satisfies every declared dependency. Existing widget-value normalization is
retained; it does not imply continued support for old Python runtimes.

## Validation and remaining checks

Use the focused export/archive/widget tests plus `test_runtime_integration.py`.
Do not collect `tests/test_watchdog.py`: it is a historical upload-at-import demo.
Run the AiiDAlab app-discovery audit before and after tests in a deployed checkout.
Refresh editable package metadata without upgrading dependencies, and verify
`Requires-Python`, `Requires-Dist`, the `aiida_openbis` import and `pip check`.

After changing branches, restart the app kernel before browser validation.
No live exports, deletions or scientific-node changes are part of this merge.
The integration contains #120 and #123–#127. Once incorporated, those parent
PRs must be reconciled by content rather than merged again. Preserve their
reviewed heads and test evidence before cleaning merged task branches.

Before production, still review:

- Fabio's archive reimport validation and integrated GUI smoke tests.
- The intermittent large-upload BrokenPipe: success with diagnostics does not
  establish its cause or exclude an instrumentation timing effect.
- Explicit **Converged: Yes / No**, with no default and export blocked until
  one is selected; **No** must remain valid. This UI change is deferred.
- Guided handling of obsolete origin extras and diagnostic-log retention.
