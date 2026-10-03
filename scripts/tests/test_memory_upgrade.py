#!/usr/bin/env python3
"""Check legacy migration, retained records, backups and interrupted writes."""

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import memory_upgrade
from memory_catalog import MemoryCatalog, MemoryCatalogError, MemoryChange
from memory_format import ENTRY_DELIMITER, parse_entries, render_entry
from memory_upgrade import BACKUP_FILENAME, upgrade_memory_files


def seed(root: Path) -> MemoryCatalog:
    memory_dir = root / "memories"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("Project fact", encoding="utf-8")
    (memory_dir / "USER.md").write_text("User preference", encoding="utf-8")
    records = [
        {"id": "m:old", "target": "memory", "content_hash": hashlib.sha256(b"Project fact").hexdigest(),
         "summary": "Custom release cue", "source": "AGENTS.md", "startup": "never", "tags": ["release"], "priority": 90},
        {"id": "u:old", "target": "user", "content_hash": hashlib.sha256(b"User preference").hexdigest(),
         "summary": "User preference", "startup": "always"},
    ]
    (memory_dir / "METADATA.jsonl").write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
    return MemoryCatalog(memory_dir=memory_dir, data_home=root)


def test_migration_preserves_ids_opt_out_and_unique_summary_and_source() -> None:
    with tempfile.TemporaryDirectory() as workdir:
        catalog = seed(Path(workdir))
        original = {p.name: p.read_text() for p in catalog.memory_dir.iterdir()}
        snapshot = catalog.ensure_startup_snapshot()
        entries = catalog.recall(mode="browse").entries
        assert {entry["entry_id"] for entry in entries} == {"u:old", "m:old"}
        memory = parse_entries((catalog.memory_dir / "MEMORY.md").read_text())[0]
        assert memory.content == "Custom release cue\nProject fact\nSource: AGENTS.md"
        assert memory.entry_id == "m:old" and memory.startup is False
        assert "Custom release cue" not in snapshot.text
        assert "User preference" in snapshot.text
        assert json.loads((catalog.memory_dir / BACKUP_FILENAME).read_text()) == original
        assert not (catalog.memory_dir / "METADATA.jsonl").exists()
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in catalog.memory_dir.iterdir()}
        assert not upgrade_memory_files(catalog.memory_dir)
        catalog.recall(mode="browse")
        assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in catalog.memory_dir.iterdir()}


def test_truncated_summaries_do_not_add_duplicate_lines_to_long_entries() -> None:
    contents = [
        "qmt-rpyc 0.3.1rc1 的 xtdata.get_local_data 签名以 field_list 为首参、stock_list 为第二参；沿用旧的 stock_list 首参调用会触发 get_market_data3 TypeError。",
        "qmt-rpyc 0.3.1rc1 的 xtdata.get_etf_info 中 ReplaceFlag/ReplaceRatio 返回明显垃圾值且 ReplaceBalance 为 null，不能用于 ETF 现金替代穿透；stocks.componentVolume 与 navPerCU 可用。",
    ]
    for body in contents + ["A" * 119, "A" * 120, "A" * 121, "A   " * 50 + "\r\nDetail"]:
        for target, name in (("memory", "MEMORY.md"), ("user", "USER.md")):
            with tempfile.TemporaryDirectory() as workdir:
                root = Path(workdir)
                memory_dir = root / "memories"
                memory_dir.mkdir()
                (memory_dir / name).write_bytes(body.encode())
                first_line = " ".join(body.splitlines()[0].split())
                summary = first_line if len(first_line) <= 120 else first_line[:119] + "…"
                record = {
                    "id": "old:entry", "target": target, "summary": summary,
                    "content_hash": hashlib.sha256(body.encode()).hexdigest(), "startup": "always",
                }
                (memory_dir / "METADATA.jsonl").write_text(json.dumps(record))
                catalog = MemoryCatalog(memory_dir=memory_dir, data_home=root)
                assert catalog.ensure_startup_snapshot().status == "current"
                entries = parse_entries((memory_dir / name).read_bytes().decode())
                assert len(entries) == 1 and entries[0].content == body
                assert entries[0].entry_id == "old:entry" and entries[0].startup is True
                assert catalog.recall(mode="get", entry_id="old:entry").entries[0]["content"] == body
                assert json.loads((memory_dir / BACKUP_FILENAME).read_text())[name] == body
                assert not upgrade_memory_files(memory_dir)


def test_distinct_summary_with_ellipsis_is_preserved() -> None:
    with tempfile.TemporaryDirectory() as workdir:
        catalog = seed(Path(workdir))
        metadata = catalog.memory_dir / "METADATA.jsonl"
        records = [json.loads(line) for line in metadata.read_text().splitlines()]
        records[0]["summary"] = "Custom release cue…"
        metadata.write_text("\n".join(json.dumps(record) for record in records))
        catalog.ensure_startup_snapshot()
        entry = parse_entries((catalog.memory_dir / "MEMORY.md").read_text())[0]
        assert entry.content == "Custom release cue…\nProject fact\nSource: AGENTS.md"
        assert entry.entry_id == "m:old" and entry.startup is False


def test_unmatched_and_bad_records_are_retained_and_reported() -> None:
    with tempfile.TemporaryDirectory() as workdir:
        catalog = seed(Path(workdir))
        path = catalog.memory_dir / "METADATA.jsonl"
        original = path.read_text() + '{bad json\n' + json.dumps({"target": "memory", "id": "missing", "content_hash": "gone"}) + "\n"
        path.write_text(original)
        with patch.object(memory_upgrade.logging.getLogger(memory_upgrade.__name__), "warning") as warn:
            snapshot = catalog.ensure_startup_snapshot()
        assert snapshot.status == "current" and warn.call_count >= 2
        assert path.read_text() == original
        assert json.loads((catalog.memory_dir / BACKUP_FILENAME).read_text())["METADATA.jsonl"] == original
        assert parse_entries((catalog.memory_dir / "MEMORY.md").read_text())[0].startup is False
        assert not upgrade_memory_files(catalog.memory_dir)


def test_interrupted_migration_resumes_without_replacing_backup_or_duplicating_text() -> None:
    with tempfile.TemporaryDirectory() as workdir:
        catalog = seed(Path(workdir))
        originals = {p.name: p.read_text() for p in catalog.memory_dir.iterdir()}
        original_write = memory_upgrade.atomic_write_text
        def interrupted(path, content, **kwargs):
            if path.name == "MEMORY.md":
                raise OSError("simulated interruption")
            original_write(path, content, **kwargs)
        with patch.object(memory_upgrade, "atomic_write_text", interrupted):
            try:
                catalog.ensure_startup_snapshot()
                raise AssertionError("Expected migration failure")
            except MemoryCatalogError as exc:
                assert exc.code == "MIGRATION_ERROR"
        assert (catalog.memory_dir / "METADATA.jsonl").exists()
        backup = (catalog.memory_dir / BACKUP_FILENAME).read_bytes()
        assert json.loads(backup) == originals
        assert catalog.startup_snapshot().status == "unavailable"
        assert catalog.ensure_startup_snapshot().status == "current"
        assert (catalog.memory_dir / BACKUP_FILENAME).read_bytes() == backup
        memory = parse_entries((catalog.memory_dir / "MEMORY.md").read_text())[0]
        assert memory.content.count("Custom release cue") == memory.content.count("AGENTS.md") == 1
        assert memory.startup is False
        assert not (catalog.memory_dir / "METADATA.jsonl").exists()


def test_backup_failure_leaves_all_original_files_unchanged() -> None:
    with tempfile.TemporaryDirectory() as workdir:
        catalog = seed(Path(workdir))
        original = {p.name: p.read_bytes() for p in catalog.memory_dir.iterdir()}
        with patch.object(memory_upgrade, "atomic_write_text", side_effect=PermissionError("denied")):
            try:
                catalog.ensure_startup_snapshot()
                raise AssertionError("Expected backup failure")
            except MemoryCatalogError as exc:
                assert exc.code == "MIGRATION_ERROR"
        assert {p.name: p.read_bytes() for p in catalog.memory_dir.iterdir() if p.name != ".memory.lock"} == original


def test_invalid_utf8_and_duplicate_ids_do_not_migrate() -> None:
    for damage in ("encoding", "duplicate"):
        with tempfile.TemporaryDirectory() as workdir:
            catalog = seed(Path(workdir))
            path = catalog.memory_dir / "MEMORY.md"
            if damage == "encoding":
                path.write_bytes(b"\xff")
            else:
                path.write_text('<!-- improve-entry:v1 {"id":"same"} -->\nOne' + ENTRY_DELIMITER + '<!-- improve-entry:v1 {"id":"same"} -->\nTwo')
            original = {p.name: p.read_bytes() for p in catalog.memory_dir.iterdir()}
            try:
                catalog.ensure_startup_snapshot()
                raise AssertionError("Expected migration error")
            except MemoryCatalogError as exc:
                assert exc.code == "MIGRATION_ERROR"
            assert {p.name: p.read_bytes() for p in catalog.memory_dir.iterdir() if p.name != ".memory.lock"} == original


def test_windows_line_endings_match_legacy_hashes() -> None:
    with tempfile.TemporaryDirectory() as workdir:
        catalog = seed(Path(workdir))
        path = catalog.memory_dir / "MEMORY.md"
        path.write_bytes(b"Project fact\r\nDetail")
        metadata = catalog.memory_dir / "METADATA.jsonl"
        records = [json.loads(line) for line in metadata.read_text().splitlines()]
        records[0]["content_hash"] = hashlib.sha256(b"Project fact\nDetail").hexdigest()
        metadata.write_text("\n".join(json.dumps(record) for record in records))
        catalog.ensure_startup_snapshot()
        entry = parse_entries(path.read_bytes().decode())[0]
        assert entry.entry_id == "m:old" and entry.startup is False
        assert "Project fact\r\nDetail" in entry.content


def test_manual_edits_during_migration_are_not_overwritten() -> None:
    with tempfile.TemporaryDirectory() as workdir:
        catalog = seed(Path(workdir))
        original_write = memory_upgrade.atomic_write_text
        def edited_after_backup(path, content, **kwargs):
            original_write(path, content, **kwargs)
            if path.name == BACKUP_FILENAME:
                (catalog.memory_dir / "MEMORY.md").write_text("Manual edit during migration")
        with patch.object(memory_upgrade, "atomic_write_text", edited_after_backup):
            try:
                catalog.ensure_startup_snapshot()
                raise AssertionError("Expected a concurrent edit failure")
            except MemoryCatalogError as exc:
                assert exc.code == "MIGRATION_ERROR"
        assert (catalog.memory_dir / "MEMORY.md").read_text() == "Manual edit during migration"
        assert (catalog.memory_dir / "METADATA.jsonl").exists()
        assert (catalog.memory_dir / BACKUP_FILENAME).exists()


def test_bad_record_shapes_and_existing_bad_backup_are_reported() -> None:
    for content_hash in ({"bad": "type"}, ["bad", "type"]):
        with tempfile.TemporaryDirectory() as workdir:
            catalog = seed(Path(workdir))
            metadata = catalog.memory_dir / "METADATA.jsonl"
            original = metadata.read_text() + json.dumps({"target": "memory", "content_hash": content_hash}) + "\n"
            metadata.write_text(original)
            assert catalog.ensure_startup_snapshot().status == "current"
            assert catalog.recall(mode="browse").success
            catalog.apply(MemoryChange("replace", "memory", entry_id="m:old", content="Updated fact"))
            assert metadata.read_text() == original
    with tempfile.TemporaryDirectory() as workdir:
        catalog = seed(Path(workdir))
        (catalog.memory_dir / BACKUP_FILENAME).write_text("[]")
        before = {p.name: p.read_bytes() for p in catalog.memory_dir.iterdir()}
        try:
            catalog.ensure_startup_snapshot()
            raise AssertionError("An invalid backup must block migration")
        except MemoryCatalogError as exc:
            assert exc.code == "MIGRATION_ERROR"
        assert before == {p.name: p.read_bytes() for p in catalog.memory_dir.iterdir() if p.name != ".memory.lock"}


def test_unresolved_entry_settings_block_reads_and_writes_until_repaired() -> None:
    for damage in ("source", "summary", "id", "id_type", "startup", "ambiguous", "unmatched", "bad_json"):
        with tempfile.TemporaryDirectory() as workdir:
            catalog = seed(Path(workdir))
            metadata = catalog.memory_dir / "METADATA.jsonl"
            records = [json.loads(line) for line in metadata.read_text().splitlines()]
            if damage in ("source", "summary"):
                records[0][damage] = "Section one\n§\nSection two"
            elif damage == "id":
                records[0]["id"] = "invalid id"
            elif damage == "id_type":
                records[0]["id"] = False
            elif damage == "startup":
                records[0]["startup"] = False
            elif damage == "ambiguous":
                records.append({**records[0], "id": "m:other"})
            elif damage == "unmatched":
                records[0]["content_hash"] = "missing"
            else:
                records.pop(0)
            metadata.write_text("\n".join(json.dumps(record) for record in records)
                                + ("\n{bad json" if damage == "bad_json" else ""))
            before = {p.name: p.read_bytes() for p in catalog.memory_dir.iterdir()}
            actions = (
                catalog.ensure_startup_snapshot,
                lambda: catalog.recall(mode="browse"),
                lambda: catalog.apply(MemoryChange("add", "memory", content="New fact")),
            )
            for action in actions:
                try:
                    action()
                    raise AssertionError("Unresolved entry settings must block migration")
                except MemoryCatalogError as exc:
                    assert exc.code == "MIGRATION_ERROR" and not exc.committed
                    assert "METADATA.jsonl" in str(exc) and "memory entry 1" in str(exc)
                assert catalog.startup_snapshot().status == "unavailable"
                assert before == {p.name: p.read_bytes() for p in catalog.memory_dir.iterdir() if p.name != ".memory.lock"}

            original_record = json.loads(before["METADATA.jsonl"].decode().splitlines()[0]) if damage != "bad_json" else {}
            repaired = {
                **original_record, "id": "m:old", "target": "memory",
                "content_hash": hashlib.sha256(b"Project fact").hexdigest(),
                "startup": "never", "summary": "Project fact", "source": "AGENTS.md",
            }
            user = next(record for record in records if record["target"] == "user")
            metadata.write_text(json.dumps(repaired) + "\n" + json.dumps(user))
            snapshot = catalog.ensure_startup_snapshot()
            assert snapshot.status == "current" and "Project fact" not in snapshot.text
            found = catalog.recall(mode="get", entry_id="m:old")
            assert found.entries[0]["startup"] is False
            assert not metadata.exists()


def test_plain_history_without_metadata_gets_fixed_ids_and_startup_defaults() -> None:
    with tempfile.TemporaryDirectory() as workdir:
        root = Path(workdir)
        memory_dir = root / "memories"
        memory_dir.mkdir()
        project = "Project fact\r\nDetails" + ENTRY_DELIMITER + "Second fact"
        (memory_dir / "MEMORY.md").write_bytes(project.encode())
        (memory_dir / "USER.md").write_text("User preference")
        catalog = MemoryCatalog(memory_dir=memory_dir, data_home=root)
        snapshot = catalog.ensure_startup_snapshot()
        assert all(cue in snapshot.text for cue in ("Project fact", "Second fact", "User preference"))
        entries = parse_entries((memory_dir / "MEMORY.md").read_bytes().decode())
        assert [entry.content for entry in entries] == ["Project fact\r\nDetails", "Second fact"]
        assert all(entry.entry_id and entry.startup for entry in entries)
        assert len({entry.entry_id for entry in entries}) == 2
        backup = (memory_dir / BACKUP_FILENAME).read_bytes()
        assert json.loads(backup) == {"MEMORY.md": project, "USER.md": "User preference", "METADATA.jsonl": None}
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in memory_dir.iterdir()}
        catalog.ensure_startup_snapshot()
        catalog.recall(mode="browse")
        assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in memory_dir.iterdir()}
        (memory_dir / "MEMORY.md").write_text(entries[1].raw + ENTRY_DELIMITER + entries[0].raw.replace("Project fact", "Edited fact"))
        found = catalog.recall(mode="get", entry_id=entries[0].entry_id)
        assert "Edited fact" in found.entries[0]["content"]
        assert (memory_dir / BACKUP_FILENAME).read_bytes() == backup


def test_missing_legacy_ids_are_assigned_without_changing_startup_opt_out() -> None:
    for missing in ("absent", None, ""):
        with tempfile.TemporaryDirectory() as workdir:
            catalog = seed(Path(workdir))
            path = catalog.memory_dir / "METADATA.jsonl"
            records = [json.loads(line) for line in path.read_text().splitlines()]
            for record in records:
                if missing == "absent":
                    record.pop("id")
                else:
                    record["id"] = missing
            records[1].pop("startup")
            path.write_text("\n".join(json.dumps(record) for record in records))
            snapshot = catalog.ensure_startup_snapshot()
            assert "User preference" in snapshot.text and "Custom release cue" not in snapshot.text
            entries = catalog.recall(mode="browse").entries
            assert len({entry["entry_id"] for entry in entries}) == 2
            assert all(entry["entry_id"] for entry in entries)
            memory = parse_entries((catalog.memory_dir / "MEMORY.md").read_text())[0]
            user = parse_entries((catalog.memory_dir / "USER.md").read_text())[0]
            assert memory.startup is False and user.startup is True
            assert not path.exists()


def test_missing_id_migration_resumes_with_the_same_id() -> None:
    with tempfile.TemporaryDirectory() as workdir:
        catalog = seed(Path(workdir))
        metadata = catalog.memory_dir / "METADATA.jsonl"
        records = [json.loads(line) for line in metadata.read_text().splitlines()]
        for record in records:
            record.pop("id")
        records[1]["summary"] = "Custom user cue"
        records[1]["source"] = "USER.md"
        metadata.write_text("\n".join(json.dumps(record) for record in records))
        original_write = memory_upgrade.atomic_write_text
        def interrupted(path, content, **kwargs):
            if path.name == "MEMORY.md":
                raise OSError("simulated interruption")
            original_write(path, content, **kwargs)
        with patch.object(memory_upgrade, "atomic_write_text", interrupted):
            try:
                catalog.ensure_startup_snapshot()
                raise AssertionError("Expected migration failure")
            except MemoryCatalogError as exc:
                assert exc.code == "MIGRATION_ERROR"
        user_before = (catalog.memory_dir / "USER.md").read_bytes()
        backup = (catalog.memory_dir / BACKUP_FILENAME).read_bytes()
        assert catalog.ensure_startup_snapshot().status == "current"
        assert (catalog.memory_dir / "USER.md").read_bytes() == user_before
        assert (catalog.memory_dir / BACKUP_FILENAME).read_bytes() == backup
        assert not metadata.exists()


def test_plain_entries_avoid_existing_ids_and_preserve_existing_blocks() -> None:
    with tempfile.TemporaryDirectory() as workdir:
        memory_dir = Path(workdir)
        reserved_id = "m:1791028800:111111111111"
        new_id = "m:1791028800:222222222222"
        existing = '  <!-- improve-entry:v1 {"startup":false, "id":"' + reserved_id + '"} -->\r\nExisting fact\r\n'
        path = memory_dir / "MEMORY.md"
        path.write_bytes(("New fact" + ENTRY_DELIMITER + existing).encode())
        with patch.object(memory_upgrade, "new_entry_id", side_effect=[reserved_id, new_id]):
            assert upgrade_memory_files(memory_dir)
        entries = parse_entries(path.read_bytes().decode())
        assert entries[0].entry_id == new_id and entries[0].startup is True
        assert entries[1].raw == existing and entries[1].startup is False
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in memory_dir.iterdir()}
        assert not upgrade_memory_files(memory_dir)
        assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in memory_dir.iterdir()}


def test_empty_and_already_marked_stores_do_not_create_migration_files() -> None:
    for text in (None, "", "\n\n", render_entry("Existing fact", "m:existing", False)):
        with tempfile.TemporaryDirectory() as workdir:
            memory_dir = Path(workdir)
            if text is not None:
                (memory_dir / "MEMORY.md").write_text(text)
            before = {p.name: p.read_bytes() for p in memory_dir.iterdir()}
            assert not upgrade_memory_files(memory_dir)
            assert before == {p.name: p.read_bytes() for p in memory_dir.iterdir()}


def test_generated_ids_do_not_take_ids_from_later_legacy_records() -> None:
    with tempfile.TemporaryDirectory() as workdir:
        catalog = seed(Path(workdir))
        path = catalog.memory_dir / "METADATA.jsonl"
        records = [json.loads(line) for line in path.read_text().splitlines()]
        reserved_id = "m:1791028800:111111111111"
        new_id = "u:1791028800:222222222222"
        records[0]["id"] = reserved_id
        records[1].pop("id")
        path.write_text("\n".join(json.dumps(record) for record in records))
        with patch.object(memory_upgrade, "new_entry_id", side_effect=[reserved_id, new_id]):
            assert catalog.ensure_startup_snapshot().status == "current"
        memory = parse_entries((catalog.memory_dir / "MEMORY.md").read_text())[0]
        user = parse_entries((catalog.memory_dir / "USER.md").read_text())[0]
        assert memory.entry_id == reserved_id and user.entry_id == new_id


def test_migration_times_mean_id_creation_and_record_save_time() -> None:
    with tempfile.TemporaryDirectory() as workdir:
        catalog = seed(Path(workdir))
        metadata = catalog.memory_dir / "METADATA.jsonl"
        records = [json.loads(line) for line in metadata.read_text().splitlines()]
        records[1].pop("id")
        metadata.write_text("\n".join(json.dumps(record) for record in records))
        with patch.object(memory_upgrade, "unix_timestamp", return_value=1791028800):
            assert catalog.ensure_startup_snapshot().status == "current"
        user = parse_entries((catalog.memory_dir / "USER.md").read_text())[0]
        memory = parse_entries((catalog.memory_dir / "MEMORY.md").read_text())[0]
        assert user.entry_id.startswith("u:1791028800:") and user.updated_at == 1791028800
        assert memory.entry_id == "m:old" and memory.updated_at == 1791028800
        with patch.object(memory_upgrade, "unix_timestamp", return_value=1791115200):
            assert not upgrade_memory_files(catalog.memory_dir)
        assert parse_entries((catalog.memory_dir / "USER.md").read_text())[0] == user


def test_previous_summary_cache_rebuilds_and_migrates_plain_history() -> None:
    with tempfile.TemporaryDirectory() as workdir:
        root = Path(workdir)
        catalog = MemoryCatalog(memory_dir=root / "memories", data_home=root)
        catalog.memory_dir.mkdir()
        (catalog.memory_dir / "MEMORY.md").write_text("Plain history")
        records = catalog._reconcile_entries()
        catalog._write_summary(catalog._revision_for(records), records)
        summary_path = catalog.memory_dir / "SUMMARY.md"
        old_summary = summary_path.read_text().replace("improve-summary:v4", "improve-summary:v3")
        summary_path.write_text(old_summary)
        state_path = catalog.memory_dir / ".summary-state.json"
        state = json.loads(state_path.read_text())
        state.update(format_version=3, summary_sha256=hashlib.sha256(old_summary.encode()).hexdigest())
        state_path.write_text(json.dumps(state))
        assert catalog.startup_snapshot().status == "unavailable"
        assert "Plain history" in catalog.ensure_startup_snapshot().text
        entry = parse_entries((catalog.memory_dir / "MEMORY.md").read_text())[0]
        assert entry.entry_id and entry.startup is True
        assert json.loads(state_path.read_text())["format_version"] == 4


ALL_TESTS = [value for name, value in list(globals().items()) if name.startswith("test_") and callable(value)]

if __name__ == "__main__":
    for test in ALL_TESTS:
        test()
        print(f"  PASS  {test.__name__}")
    print(f"\n{len(ALL_TESTS)} passed, 0 failed, {len(ALL_TESTS)} total")
