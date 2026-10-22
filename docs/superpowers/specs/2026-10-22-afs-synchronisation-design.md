# Design Document: AFS Folder Synchronisation Interface

**Date**: 2026-10-22
**Status**: Approved Specification
**Target Branch**: `feature/create-synchronisation-interface`
**Repository**: `/home/jovyan/apps/aiidalab-openbis` inside container `aiidalab-pilot-phase-7.0`

---

## 1. Intent and Why
In the openBIS and AiiDAlab workflow, scientific raw data (e.g., scanning probe microscopy scans, measurement data) is stored in the openBIS Advanced File Server (AFS) attached to specific openBIS objects (samples or experiments). Before researchers can process this data and register processed measurements back into openBIS via the AiiDAlab Measurement Uploader, the raw files must be mirrored into the local AiiDAlab filesystem.

This feature provides a dedicated graphical interface within the AiiDAlab-openBIS app that establishes an automated, continuous, one-way synchronization process from a chosen openBIS AFS folder into a local AiiDAlab folder.

---

## 2. Goals, Non-Goals, and Anti-Goals

### Goals
- Provide a clear, discoverable entry point from the "Experiments" section in `0_home.ipynb`.
- Follow the app's established design pattern: a clean Jupyter Notebook interface (`6_synchronisation.ipynb`) paired with modular widget code in `src/`.
- Authenticate and connect to openBIS using existing ELN configuration via `src.utils.connect_openbis_aiida()`.
- Search for openBIS objects (Samples / Experiments) and browse/select directories in the object's AFS space using `pybis.AfsClient`.
- Select local destination folder in AiiDAlab.
- Allow user to configure poll interval down to 5 seconds (default: 60s).
- Run synchronization as an independent, detached background process that continues running even if the user closes the notebook.
- **Mirroring semantics**: Modifications, creations, and deletions on the openBIS AFS side are mirrored to AiiDAlab (deleting a file in AFS deletes the local file in AiiDAlab).
- Prevent duplicate or conflicting synchronizations: if an AFS folder is already being synchronized, clearly notify the user where it is already synced (including target path and PID) and disallow duplicating the sync.
- Track active synchronization jobs in a JSON registry in `logs/active_synchronisations.json`.
- Provide an "Active Synchronisations" tab allowing users to inspect running sync jobs, check sync status/timestamps, and terminate/stop sync jobs cleanly.

### Non-Goals
- Two-way synchronization: Modifications in AiiDAlab are **not** pushed back to openBIS AFS. It is strictly one-way (openBIS AFS $\rightarrow$ AiiDAlab).
- Direct integration into Measurement Uploader: This tool feeds local folders that can subsequently be selected in the Measurement Uploader.

### Anti-Goals
- Blocking the Jupyter kernel: The synchronization loop must never execute directly in the notebook's interactive thread.
- Silent file overwriting or conflicts across jobs: Never permit two simultaneous background processes to sync the same AFS folder or target the same destination folder.

---

## 3. Architecture & User Experience

### 3.1 Entry Point & Configuration
- **File**: `config/config.json`
- Under `home_page.enable_links.Experiments` and `home_page.disable_links.Experiments`, add:
  ```html
  <li><a href='6_synchronisation.ipynb' target='_blank' style='font-size: 13px;'>Folder synchronisation (AFS)</a></li>
  ```
- If the openBIS session is disconnected, the link is grayed out / disabled consistent with other experiment interfaces.

### 3.2 Notebook Layout (`6_synchronisation.ipynb`)
The notebook follows the layout pattern of `1_sample_preparation.ipynb`:
1. **Introduction & Explanation Section**:
   - Header explaining the tool's purpose: automated one-way sync from openBIS AFS to AiiDAlab local storage for raw data processing.
2. **Tabbed View (`ipw.Tab`)**:
   - **Tab 1: Setup Synchronisation**
   - **Tab 2: Active Synchronisations**
3. **Footer**:
   - Standard "Home" button returning to `0_home.ipynb` (`close_notebook` callback).

### 3.3 Tab 1: Setup Synchronisation Details
- **Object Search**:
  - Input field for Sample / Object code or identifier (e.g. `/DEFAULT/RAW_EXP/SAMPLE_101` or permId).
  - Search button: Queries openBIS to validate object existence and retrieve permId.
- **AFS Directory Selection**:
  - Button to query AFS (`AfsClient.list(owner=perm_id, source="/", recursively=True)`).
  - Dropdown populated with all directory paths found in the object's AFS space (including `/` for root).
- **AiiDAlab Destination Folder**:
  - Text input (defaulting to `/home/jovyan/data/<sample_code>/...`) with validation ensuring valid local path.
- **Poll Interval Selector**:
  - `ipw.BoundedIntText` or `ipw.IntSlider`: Range 5s to 3600s, default 60s.
- **Conflict & Validation Banner**:
  - Dynamic alert box.
  - If the chosen `(owner, afs_path)` is currently active (`status == "RUNNING"`) in `logs/active_synchronisations.json`:
    - Shows an amber/red warning: *"⚠️ AFS folder '{afs_path}' on object '{owner}' is already being synchronized to '{local_path}' (PID: {pid}). Duplicate synchronisation is not allowed."*
    - The "Start Synchronisation" button is disabled.
  - If the chosen `local_path` is already targeted by another active sync job:
    - Shows an alert preventing destination collisions.
- **Start Synchronisation Button**:
  - Launches background process, writes record to `logs/active_synchronisations.json`, displays success notification, and switches tab / refreshes Active Synchronisations.

### 3.4 Tab 2: Active Synchronisations Details
- Displays a table/list of all currently running and stopped synchronization jobs.
- Columns / Card details:
  - Object Identifier & PermId
  - Source AFS Folder
  - Target AiiDAlab Folder
  - Poll Interval
  - Process PID & Status (`RUNNING` / `STOPPED`)
  - Started timestamp & Last synced timestamp
  - Action buttons:
    - **Stop Sync**: (Visible for running jobs) Sends `SIGTERM` to the worker PID and updates registry status to `STOPPED`.
    - **Dismiss**: (Visible for stopped jobs) Removes the stopped record from `logs/active_synchronisations.json`.
- **Refresh Button**: Scans running PIDs (via `os.kill(pid, 0)`), cleans up dead processes by marking them `STOPPED`, and refreshes the view.

---

## 4. Backend Synchronization Process

### 4.1 Worker Script (`src/sync_afs_worker.py`)
- Executed via `subprocess.Popen([sys.executable, "src/sync_afs_worker.py", "--config", job_config_path], start_new_session=True)`.
- Arguments / Config:
  - `owner` (permId)
  - `source_path` (AFS folder)
  - `destination_path` (local path)
  - `interval` (seconds, $\ge 5$)
  - `job_id`
  - `log_file`
- Re-reads or uses openBIS session credentials (URL and token from `~/.aiidalab/aiidalab-eln-config.json` via `utils.connect_openbis_aiida()`).
- Path translation:
  - Files are mapped relative to the chosen `source_path`. For example, syncing `/raw_scans/run1` to `/home/jovyan/data/run1` will place `/raw_scans/run1/scan.dat` directly at `/home/jovyan/data/run1/scan.dat` (not double-nested).
- Synchronization & Mirroring Loop:
  1. Verify openBIS / AFS connectivity.
  2. Query remote files: `remote_files = afs_client.list(owner, source_path, recursively=True)`.
  3. Map remote file paths to relative local paths and set of expected relative files.
  4. **Download / Update**: For each remote file:
     - If directory, `os.makedirs(local_dir, exist_ok=True)`.
     - If regular file: compare local file existence, size, and timestamp. If missing or different, download the file content via `afs_client.read()` chunks.
  5. **Mirror Deletions**: Walk the local `destination_path`. If a local file or directory does not exist in `remote_files`, delete it locally (`os.remove()` / `os.rmdir()`).
  6. Update `last_synced` timestamp and file count in `logs/active_synchronisations.json`.
  7. Sleep for `poll_interval` seconds.
  8. Handles `SIGTERM` / `SIGINT` gracefully to mark status `STOPPED` and cleanly exit.

### 4.2 State Registry (`logs/active_synchronisations.json`)
Structure:
```json
{
  "jobs": {
    "<job_id>": {
      "job_id": "sync-1730000000",
      "pid": 12345,
      "owner": "20261015112345678-101",
      "object_identifier": "/DEFAULT/RAW_EXP/SAMPLE_101",
      "afs_path": "/raw_stm_scans/run_1",
      "local_path": "/home/jovyan/data/openbis_raw_scans/run_1",
      "poll_interval": 10,
      "status": "RUNNING",
      "started_at": "2026-10-22T10:30:00",
      "last_synced": "2026-10-22T10:31:20",
      "files_synced": 12
    }
  }
}
```

---

## 5. Builder Calls & Technical Decisions
- **Mirroring Deletions**: Remotely deleted files and directories are deleted locally to keep AiiDAlab in exact sync with openBIS AFS.
- **Source of Truth**: openBIS AFS is the authoritative source. If an AFS file changes, it overwrites the local copy.
- **Path Mapping**: Relative paths under the selected `source_path` are mapped directly to `destination_path` to avoid redundant nested folders.
- **Stopped Job Lifecycle**: Stopping a job sets its status to `STOPPED`. A `STOPPED` job immediately frees the folder so it can be re-synced if needed. A "Dismiss" button in Tab 2 allows clearing stopped jobs from view.
- **SSL Verification**: Uses `verify=False` for local openBIS instances where certificates might be self-signed.
- **Testing**: Tests in `tests/test_synchronisation.py` verify registry CRUD operations, PID liveness checks, conflict detection, and path mapping logic.
