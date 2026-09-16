# Upload diagnostic reports

Every simulation export attempt can produce an **Upload diagnostic report**
below its completion/recovery message. Expand it and choose **Download diagnostic
report (JSON)** to share the diagnostic record with support. The export status
and retry action remain authoritative: a request can fail after the server has
already accepted the dataset. The report does not retry uploads or change the
existing recovery checks.

Restart the app's notebook kernel after updating the app to load the new code.
Browser download behavior still needs a live GUI check.

## Reading a report

The report includes a unique attempt identifier, UTC timestamps, elapsed times,
Python/library versions, local file sizes and free space, and these phases:

| Phase | What is being observed |
| --- | --- |
| `archive_creation` | Creation of the archive from the local AiiDA database |
| `archive_record` | Creation/reuse of the openBIS AiiDA provenance object |
| `remote_inventory` | An existing recovery check for expected remote content |
| `dataset_preparation` | Construction of the pyBIS dataset |
| `dataset_save` | The complete pyBIS dataset-save operation |
| `chunk_transfer` | Staging files with the pyBIS v3 upload queue |
| `dataset_registration` | The `createUploadedDataSet` request |
| `dataset_readback` | pyBIS's read-back after registration |

Chunk events include a generated request identifier, destination hostname,
numeric chunk ID/range when supplied by pyBIS, body size, duration, HTTP status
or exception classes/errno and stack locations. The first failed phase helps
localize the failure; it does **not** identify its infrastructure root cause.
For example, a `BrokenPipeError` during `chunk_transfer` alone does not establish
whether a proxy, server, network interruption, or client behavior caused it.

Accepted-byte totals count request bodies receiving HTTP 2xx from the staging
service. They are not socket-level progress, proof of archive integrity, or proof
of successful dataset registration. Failed requests may have partially sent
bytes, and response loss may leave accepted data uncounted. Request duration
includes retries performed internally by the existing HTTP adapter; individual
adapter retry attempts are not separately instrumented.

## Live and persistent logs

A private, per-attempt JSONL file is flushed as events occur:

```text
logs/upload_diagnostics/<attempt-id>.jsonl
```

Paths are anchored to the app checkout, not to the notebook working directory.
A heartbeat every 15 seconds records active request count, oldest request age,
and accepted-byte totals. This allows support to distinguish a slow/pending
request from a phase that already failed while the GUI call is still running.
The heartbeat is written to the log; it is not a live GUI progress bar.

Files are created with mode `0600`. No automatic log deletion is performed.
If the log cannot be created/written, the downloadable in-memory report remains
available and marks the local log unavailable. In-memory reports retain up to
5,000 events and count omitted events; the JSONL file is not truncated.

## Privacy and compatibility

The report deliberately omits credentials, session tokens, URLs/query strings,
headers, payloads, response bodies, arbitrary filenames/properties, and exception
messages. Exception types, numeric errno and source stack locations are retained.
Workflow/object identifiers and destination hostnames remain useful diagnostic
metadata: review a report before sharing it outside your organization.
Raw pyBIS dataset-save stdout is discarded because it can include authenticated
request details. Existing technical-error panels show exception classes/errno
instead of arbitrary backend exception messages.

Chunk instrumentation is tested with pyBIS `6.9.1.0rc1`. This version does not
expose a queue-injection hook, so instrumentation uses a private copy of its
upload method with a per-dataset observed queue. The pyBIS module, shared client,
HTTP adapter/retry policy, request bodies and TLS settings are not patched.
Unknown method implementations retain phase-level diagnostics and emit
`chunk_instrumentation_unavailable`; legacy uploads have a
`legacy_file_transfer` phase without individual chunk details.

In the tested pyBIS version, chunks are hard-coded to 10 MiB and the queue
defaults to 10 workers. This change exposes neither setting and changes neither.
Changing those values for controlled comparisons should be a separate change,
after capturing a baseline report.

When reporting a failure, attach the JSON report, describe the action taken,
and give the observed final GUI status. Administrators can correlate its UTC
interval and identifiers with server/proxy logs. A successful manual browser
upload is useful comparative evidence, but does not prove equivalence with the
pyBIS staging and registration path.
