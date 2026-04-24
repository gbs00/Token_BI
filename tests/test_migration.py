import json

from app.migration import migrate_project_data


def test_migration_copies_accounts_and_runtime_contexts(tmp_path):
    old_root = tmp_path / "old"
    app_data = tmp_path / "app-data"
    (old_root / "config").mkdir(parents=True)
    (old_root / "runtime" / "contexts" / "acc_1").mkdir(parents=True)
    (old_root / "config" / "accounts.json").write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "account_id": "acc_1",
                        "account_alias": "8754****@qq.com",
                        "masked_email": "8754****@qq.com",
                        "status": "active",
                        "session_storage_path": str(old_root / "runtime" / "contexts" / "acc_1"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = migrate_project_data(old_root=old_root, app_data_dir=app_data)

    assert result.migrated is True
    assert (app_data / "config" / "accounts.json").exists()
    assert (app_data / "runtime" / "contexts" / "acc_1").exists()
    payload = json.loads((app_data / "config" / "accounts.json").read_text(encoding="utf-8"))
    assert payload["accounts"][0]["session_storage_path"] == str(app_data / "runtime" / "contexts" / "acc_1")


def test_migration_does_not_overwrite_existing_app_data(tmp_path):
    old_root = tmp_path / "old"
    app_data = tmp_path / "app-data"
    (old_root / "config").mkdir(parents=True)
    (app_data / "config").mkdir(parents=True)
    (old_root / "config" / "accounts.json").write_text('{"accounts": []}', encoding="utf-8")
    (app_data / "config" / "accounts.json").write_text('{"accounts": [{"account_id": "existing"}]}', encoding="utf-8")

    result = migrate_project_data(old_root=old_root, app_data_dir=app_data)

    assert result.migrated is False
    assert "existing" in (app_data / "config" / "accounts.json").read_text(encoding="utf-8")
