# AFS Folder Synchronisation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a robust, one-way AFS folder synchronisation interface in the AiiDAlab-openBIS app that mirrors raw measurement folders from openBIS AFS to local AiiDAlab storage as an independent background process.

**Architecture:** A Jupyter notebook (`6_synchronisation.ipynb`) hosting an ipywidgets Tab interface (`Setup` and `Active Synchronisations`). A registry manager (`src/sync_registry.py`) manages job state and conflict detection in `logs/active_synchronisations.json`. A background worker daemon (`src/sync_afs_worker.py`) executes detached via `subprocess.Popen`, querying `pybis.AfsClient` at user-defined poll intervals, incrementally downloading new/modified files, and mirroring deletions.

**Tech Stack:** Python 3.9+, Jupyter Notebook, ipywidgets, pybis (`AfsClient`), pytest, unittest.mock.

**Spec:** `docs/superpowers/specs/2026-10-22-afs-synchronisation-design.md`

## Global Constraints
- Target branch: `feature/create-synchronisation-interface`
- Repository directory: `/home/jovyan/apps/aiidalab-openbis` in container `aiidalab-pilot-phase-7.0`
- Python version floor: 3.9
- One-way sync strictly: openBIS AFS $\rightarrow$ AiiDAlab (never push local changes to openBIS AFS)
- Incremental/differential download: Never re-download an unchanged file whose size matches the remote file
- Mirroring deletion: Files/directories deleted on openBIS AFS are deleted locally in AiiDAlab
- Minimum poll interval: 5 seconds (default: 60s)
- Background execution: Detached process via `start_new_session=True` so sync continues if notebook closes
- Conflict policy: Block duplicate sync of the same active `(owner, afs_path)` or duplicate targeting of the same `local_path`

## Review Focus
1. *Path normalization with leading/trailing slashes*: Remote paths from `afs_client.list()` or user input may have varied slashes (e.g., `/run1/` vs `run1`). Path normalization must produce the exact relative structure without empty path segments or double-nesting.
2. *Local nested directory deletion*: When mirroring remote deletions, deleting a non-empty directory locally must not crash or leave orphaned files.
3. *Stale/dead PID handling*: When the worker process is killed or abruptly ends, `sync_liveness()` must detect the dead PID and mark the job `STOPPED` rather than crashing or hanging.
4. *Poll interval boundary clamping*: If a user enters an interval $< 5$ seconds, the system must clamp it to 5 seconds.
5. *Clean resumption of stopped jobs*: Resuming a previously stopped sync when all local files already exist must perform 0 downloads, 0 deletions, and update `last_synced` cleanly.

---

### Task 1: Synchronization Registry & Conflict Detection (`src/sync_registry.py`)

**Files:**
- Create: `src/sync_registry.py`
- Test: `tests/test_synchronisation.py`

**Interfaces:**
- Consumes: Standard Python `json`, `os`, `signal`, `pathlib.Path`, `datetime`.
- Produces:
  - `load_registry(registry_path: Path) -> dict`
  - `save_registry(data: dict, registry_path: Path) -> None`
  - `find_conflict(owner: str, afs_path: str, local_path: str, registry_path: Path) -> Optional[dict]`
  - `register_job(job_info: dict, registry_path: Path) -> None`
  - `update_job(job_id: str, updates: dict, registry_path: Path) -> None`
  - `stop_job(job_id: str, registry_path: Path) -> bool`
  - `dismiss_job(job_id: str, registry_path: Path) -> bool`
  - `sync_liveness(registry_path: Path) -> None`

- [ ] **Step 1: Write the failing tests for registry operations and conflict detection**

```python
# In tests/test_synchronisation.py
import pytest
from pathlib import Path
from src import sync_registry

def test_registry_lifecycle_and_conflict(tmp_path):
    reg_file = tmp_path / "active_synchronisations.json"

    # Empty registry
    assert sync_registry.load_registry(reg_file) == {"jobs": {}}

    # Register job 1
    job1 = {
        "job_id": "job-1",
        "pid": 999999,
        "owner": "SAMPLE_1",
        "object_identifier": "/SPACE/EXP/SAMPLE_1",
        "afs_path": "/scans/run1",
        "local_path": "/data/run1",
        "poll_interval": 10,
        "status": "RUNNING",
    }
    sync_registry.register_job(job1, reg_file)

    # Conflict checks
    conflict_afs = sync_registry.find_conflict("SAMPLE_1", "/scans/run1/", "/other/dir", reg_file)
    assert conflict_afs is not None
    assert conflict_afs["job_id"] == "job-1"

    conflict_local = sync_registry.find_conflict("SAMPLE_2", "/scans/run2", "/data/run1", reg_file)
    assert conflict_local is not None
    assert conflict_local["job_id"] == "job-1"

    # No conflict for different afs & local
    assert sync_registry.find_conflict("SAMPLE_2", "/scans/run2", "/data/run2", reg_file) is None

    # Stop job
    sync_registry.update_job("job-1", {"status": "STOPPED"}, reg_file)
    # Stopped job should no longer cause active conflict
    assert sync_registry.find_conflict("SAMPLE_1", "/scans/run1", "/data/run1", reg_file) is None

    # Dismiss job
    assert sync_registry.dismiss_job("job-1", reg_file) is True
    assert "job-1" not in sync_registry.load_registry(reg_file)["jobs"]

def test_sync_liveness_marks_dead_pid_stopped(tmp_path):
    reg_file = tmp_path / "active_synchronisations.json"
    job = {
        "job_id": "job-dead",
        "pid": 99999999,  # Definitely non-existent PID
        "owner": "SAMPLE_1",
        "afs_path": "/run1",
        "local_path": "/data/run1",
        "status": "RUNNING",
    }
    sync_registry.register_job(job, reg_file)
    sync_registry.sync_liveness(reg_file)
    data = sync_registry.load_registry(reg_file)
    assert data["jobs"]["job-dead"]["status"] == "STOPPED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_synchronisation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.sync_registry'`

- [ ] **Step 3: Implement `src/sync_registry.py`**

Implement `load_registry`, `save_registry`, `normalize_path`, `find_conflict`, `register_job`, `update_job`, `stop_job` (sending `os.kill(pid, signal.SIGTERM)`), `dismiss_job`, and `sync_liveness` with safe file read/write and PID checking.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_synchronisation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sync_registry.py tests/test_synchronisation.py
git commit -m "feat(sync): add synchronization registry and conflict detection"
```

---

### Task 2: Background Sync Engine & Mirroring (`src/sync_afs_worker.py`)

**Files:**
- Create: `src/sync_afs_worker.py`
- Modify: `tests/test_synchronisation.py`

**Interfaces:**
- Consumes: `src.sync_registry`, `pybis.AfsClient`, `src.utils.connect_openbis_aiida`
- Produces:
  - `compute_relative_path(file_path: str, source_path: str) -> str`
  - `sync_once(afs_client, owner: str, source_path: str, destination_path: str) -> dict`
  - `run_worker(config: dict) -> None`
  - CLI entrypoint: `python src/sync_afs_worker.py --config <config_file_path>`

- [ ] **Step 1: Write the failing tests for path mapping, incremental skip, and deletion mirroring**

```python
# In tests/test_synchronisation.py
from unittest.mock import MagicMock
from src.sync_afs_worker import compute_relative_path, sync_once

def test_compute_relative_path():
    assert compute_relative_path("/raw/run1/scan.dat", "/raw/run1") == "scan.dat"
    assert compute_relative_path("/raw/run1/sub/scan.dat", "/raw/run1/") == "sub/scan.dat"
    assert compute_relative_path("/scan.dat", "/") == "scan.dat"
    assert compute_relative_path("scan.dat", "") == "scan.dat"

def test_sync_once_incremental_and_deletion(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()

    # Pre-existing local file that will be deleted because it is not on AFS
    stale_file = dest / "stale.dat"
    stale_file.write_text("old data")

    # Mock remote AFS files
    mock_file1 = MagicMock()
    mock_file1.directory = False
    mock_file1.path = "/scans/run1/scan1.dat"
    mock_file1.size = 12
    mock_file1.name = "scan1.dat"

    mock_client = MagicMock()
    mock_client.list.return_value = [mock_file1]
    mock_client.read.return_value = b"hello remote"

    # First sync: downloads scan1.dat, deletes stale.dat
    stats1 = sync_once(mock_client, "SAMPLE_1", "/scans/run1", str(dest))
    assert stats1["downloaded"] == 1
    assert stats1["deleted"] == 1
    assert not stale_file.exists()
    assert (dest / "scan1.dat").read_bytes() == b"hello remote"

    # Second sync: scan1.dat already exists with matching size -> skipped!
    mock_client.read.reset_mock()
    stats2 = sync_once(mock_client, "SAMPLE_1", "/scans/run1", str(dest))
    assert stats2["downloaded"] == 0
    assert stats2["skipped"] == 1
    assert stats2["deleted"] == 0
    mock_client.read.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_synchronisation.py -k "test_compute_relative_path or test_sync_once_incremental_and_deletion" -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.sync_afs_worker'`

- [ ] **Step 3: Implement `src/sync_afs_worker.py`**

Implement:
1. `compute_relative_path` using normalized POSIX paths.
2. `sync_once`:
   - Queries `afs_client.list(owner, source_path, recursively=True)`.
   - Iterates remote entries: creates subdirectories; checks local file size matching `remote_file.size`. If matches, skip. Otherwise reads chunks via `afs_client.read()` and writes to local file.
   - Scans local destination bottom-up: if local file/directory not in remote set, removes it (`os.remove` / `shutil.rmtree`).
   - Returns statistics (`{"downloaded": d, "skipped": s, "deleted": del}`).
3. Signal handling (`SIGTERM`, `SIGINT`) and daemon loop `run_worker(config)` executing every `poll_interval` ($\ge 5$s) and updating registry via `sync_registry.update_job`.
4. CLI argument parsing (`--config /path/to/job_spec.json`).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_synchronisation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sync_afs_worker.py tests/test_synchronisation.py
git commit -m "feat(sync): implement background sync worker with incremental and mirroring semantics"
```

---

### Task 3: Interactive UI Widgets (`src/synchronisation_widgets.py`)

**Files:**
- Create: `src/synchronisation_widgets.py`
- Modify: `tests/test_synchronisation.py`

**Interfaces:**
- Consumes: `src.sync_registry`, `src.sync_afs_worker`, `pybis.Openbis`, `pybis.AfsClient`, `ipywidgets`
- Produces:
  - `SetupSyncWidget(openbis_session, on_job_started=None)`
  - `ActiveSyncsWidget(on_change=None)`
  - `SynchronisationMainWidget(openbis_session)`

- [ ] **Step 1: Write test for UI widget initialization and conflict validation logic**

```python
# In tests/test_synchronisation.py
from unittest.mock import MagicMock
from src import synchronisation_widgets, sync_registry

def test_setup_sync_widget_conflict_detection(tmp_path):
    reg_file = tmp_path / "active_synchronisations.json"
    job = {
        "job_id": "job-test",
        "pid": 1111,
        "owner": "SMP_1",
        "afs_path": "/run1",
        "local_path": "/local/run1",
        "status": "RUNNING",
    }
    sync_registry.register_job(job, reg_file)

    mock_session = MagicMock()
    widget = synchronisation_widgets.SetupSyncWidget(
        openbis_session=mock_session,
        registry_path=reg_file
    )

    # Check conflict detection method
    conflict = widget.check_conflict("SMP_1", "/run1", "/other/path")
    assert conflict is not None
    assert "already being synchronized" in widget.conflict_html.value
    assert widget.start_button.disabled is True

    # Check valid path
    widget.check_conflict("SMP_1", "/run2", "/local/run2")
    assert widget.conflict_html.value == ""
    assert widget.start_button.disabled is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_synchronisation.py -k "test_setup_sync_widget_conflict_detection" -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.synchronisation_widgets'`

- [ ] **Step 3: Implement `src/synchronisation_widgets.py`**

Implement:
1. `SetupSyncWidget`:
   - Search box for object (queries `openbis_session.get_sample` or `get_experiment`).
   - AFS folder loader using `AfsClient.list()`, populating dropdown.
   - Local path text input.
   - Poll interval `BoundedIntText(value=60, min=5, max=3600)`.
   - Real-time conflict checking banner calling `find_conflict` on changes.
   - Start button spawning detached background worker: `subprocess.Popen([sys.executable, "src/sync_afs_worker.py", "--config", ...], start_new_session=True)`.
2. `ActiveSyncsWidget`:
   - Job cards rendering running and stopped jobs.
   - "Stop Sync" sending SIGTERM via `sync_registry.stop_job`.
   - "Resume Sync" relaunching background worker for stopped job.
   - "Dismiss" removing stopped job via `sync_registry.dismiss_job`.
   - "Refresh" calling `sync_registry.sync_liveness`.
3. `SynchronisationMainWidget`:
   - Wraps `ipw.Tab(children=[setup_widget, active_widget])` with styled headers.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_synchronisation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synchronisation_widgets.py tests/test_synchronisation.py
git commit -m "feat(sync): implement SetupSyncWidget, ActiveSyncsWidget and SynchronisationMainWidget"
```

---

### Task 4: Notebook Interface & Menu Integration (`6_synchronisation.ipynb` & `config/config.json`)

**Files:**
- Create: `6_synchronisation.ipynb`
- Modify: `config/config.json`
- Test: `tests/test_synchronisation.py`

**Interfaces:**
- Consumes: `src.utils.connect_openbis_aiida`, `src.synchronisation_widgets.SynchronisationMainWidget`
- Produces:
  - Working Jupyter Notebook `6_synchronisation.ipynb`
  - Discoverable link under Experiments in `0_home.ipynb`

- [ ] **Step 1: Write test verifying config.json link and notebook structure**

```python
# In tests/test_synchronisation.py
import json

def test_config_json_contains_synchronisation_link():
    with open("config/config.json") as f:
        cfg = json.load(f)
    enable_exp = "".join(cfg["home_page"]["enable_links"]["Experiments"])
    assert "6_synchronisation.ipynb" in enable_exp
    assert "Folder synchronisation (AFS)" in enable_exp

    disable_exp = "".join(cfg["home_page"]["disable_links"]["Experiments"])
    assert "6_synchronisation.ipynb" in disable_exp

def test_notebook_valid_json():
    with open("6_synchronisation.ipynb") as f:
        nb = json.load(f)
    assert nb["nbformat"] == 4
    cell_sources = "".join("".join(c["source"]) for c in nb["cells"])
    assert "SynchronisationMainWidget" in cell_sources
    assert "connect_openbis_aiida" in cell_sources
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_synchronisation.py -k "test_config_json or test_notebook_valid_json" -v`
Expected: FAIL

- [ ] **Step 3: Update `config/config.json` and generate `6_synchronisation.ipynb`**

1. In `config/config.json`, add `<li><a href='6_synchronisation.ipynb' target='_blank' style='font-size: 13px;'>Folder synchronisation (AFS)</a></li>` to enabled and disabled experiment links.
2. Create `6_synchronisation.ipynb` using standard nbformat 4 with:
   - Header & explanation markdown
   - Import of `src.utils` and `src.synchronisation_widgets`
   - Connection check via `utils.connect_openbis_aiida()`
   - Display of `SynchronisationMainWidget` and Home button returning to `0_home.ipynb`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_synchronisation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config/config.json 6_synchronisation.ipynb tests/test_synchronisation.py
git commit -m "feat(sync): add 6_synchronisation.ipynb and update config.json experiment links"
```

---

### Task 5: End-to-End Verification & Liveness in Docker Container

**Files:**
- Test: Full integration test suite `tests/test_synchronisation.py`

**Interfaces:**
- Consumes: Running openBIS & AFS instance in `aiidalab-pilot-phase-7.0` container

- [ ] **Step 1: Run all tests in the container environment**

Run: `docker exec -w /home/jovyan/apps/aiidalab-openbis aiidalab-pilot-phase-7.0 pytest tests/test_synchronisation.py -v`
Expected: All tests PASS with 100% success.

- [ ] **Step 2: Verify pre-commit hooks pass cleanly in container**

Run: `docker exec -w /home/jovyan/apps/aiidalab-openbis aiidalab-pilot-phase-7.0 pre-commit run --all-files`
Expected: All pre-commit checks PASS.

- [ ] **Step 3: Verify git status is clean**

Run: `docker exec -w /home/jovyan/apps/aiidalab-openbis aiidalab-pilot-phase-7.0 git status`
Expected: Clean working tree on branch `feature/create-synchronisation-interface`.
