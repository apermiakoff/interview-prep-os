from app.backup import backup
from app.db import connect, init_db


def test_sqlite_backup_is_readable(tmp_path):
    source = tmp_path / "source.db"
    init_db(source)
    target = backup(source, tmp_path / "backups")
    assert target.exists()
    with connect(target) as connection:
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 2
