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

    # Conflict checks: same owner & afs_path with varied slash
    conflict_afs = sync_registry.find_conflict(
        "SAMPLE_1", "/scans/run1/", "/other/dir", reg_file
    )
    assert conflict_afs is not None
    assert conflict_afs["job_id"] == "job-1"

    # Conflict checks: same local path
    conflict_local = sync_registry.find_conflict(
        "SAMPLE_2", "/scans/run2", "/data/run1/", reg_file
    )
    assert conflict_local is not None
    assert conflict_local["job_id"] == "job-1"

    # No conflict for different afs & local
    assert (
        sync_registry.find_conflict("SAMPLE_2", "/scans/run2", "/data/run2", reg_file)
        is None
    )

    # Stop job
    sync_registry.update_job("job-1", {"status": "STOPPED"}, reg_file)
    # Stopped job should no longer cause active conflict
    assert (
        sync_registry.find_conflict("SAMPLE_1", "/scans/run1", "/data/run1", reg_file)
        is None
    )

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
