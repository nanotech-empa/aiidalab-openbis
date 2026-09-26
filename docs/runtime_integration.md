# Python 3.12 integration

This branch combines the following remote revisions, checked on 2026-09-17:

| Source | Revision | Role |
| --- | --- | --- |
| `master` | `33a92c0` | Current upstream, including process-template ordering |
| `fix/upload-diagnostics` (#127) | `b55ad0e` | Authoritative simulation import/export implementation and diagnostics |
| `fix-package-discovery-py312` (#114) | `2b91a2c` | Package discovery and ipywidgets startup fixes |

The diagnostic branch already contains the simulation stack through #126.
The integration retains that implementation, including single-root archive
splitting, scalar UUIDs, provenance/origin handling, incomplete-export recovery,
molecule lookup and per-upload diagnostic reports. No transport tuning is added.

Merge conflicts preserve the recent app-anchored log paths, experiment/project
selection, process-template ordering, observable dataset names, empty-action
guard and instrument locking. The packaging branch's safe accordion update
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
The tested current environment uses Python 3.12.11, AiiDA 2.8.0, AiiDAlab 26.5.2,
ipywidgets 8.1.8 and pyBIS 6.9.1.0rc1. Existing widget-value normalization is
retained; it does not imply continued support for old Python runtimes.

## Validation and remaining checks

Use the focused export/archive/widget tests plus `test_runtime_integration.py`.
Do not collect `tests/test_watchdog.py`: it is a historical upload-at-import demo.
Run the AiiDAlab app-discovery audit before and after tests in a deployed checkout.
Refresh editable package metadata without upgrading dependencies, and verify
`Requires-Python`, `Requires-Dist`, the `aiida_openbis` import and `pip check`.

After changing branches, restart the app kernel before browser validation.
No live exports, deletions or scientific-node changes are part of this merge.
The original review branches/PRs remain available for comparison; integration
does not mean they have been merged into upstream `master`.

Before production, still review:

- Fabio's archive reimport validation and integrated GUI smoke tests.
- The intermittent large-upload BrokenPipe: success with diagnostics does not
  establish its cause or exclude an instrumentation timing effect.
- Explicit **Converged: Yes / No**, with no default and export blocked until
  one is selected; **No** must remain valid. This UI change is deferred.
- Guided handling of obsolete origin extras and diagnostic-log retention.
