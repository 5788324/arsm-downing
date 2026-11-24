"""Bound startup I/O without changing durable download decisions."""
import asyncio
from datetime import datetime
from pathlib import Path

from core.config import ConfigManager
from core.database import LibraryVault
from core.network import NetworkKernel
from core.orchestrator import Orchestrator
from core.services.download_service import DownloadService


def test_recovery_checks_keys_without_loading_json(tmp_path):
    db = LibraryVault(tmp_path / 'history.db')
    try:
        for key, date in [('RJ00000001', '2000-01-01'),
                          ('RJ00000002', datetime.now().isoformat()),
                          ('RJ00000003', 'invalid')]:
            db.conn.execute(
                'INSERT INTO metadata_cache(rj_id,fetched_at,metadata_json,tracks_json) '
                'VALUES(?,?,?,?)', (key, date, 'x' * 100000, 'y' * 100000))
        queries = []
        db.conn.set_trace_callback(queries.append)
        assert db.get_recovery_metadata_ids() == {'RJ00000001', 'RJ00000002'}
        assert len(queries) == 1
        assert 'metadata_json' not in queries[0]
        assert 'tracks_json' not in queries[0]
    finally:
        db.close()


def test_startup_does_not_read_full_cache_per_work_or_auto_enqueue(tmp_path):
    db = LibraryVault(tmp_path / 'history.db')
    config = ConfigManager()
    config.output_dir = tmp_path
    config.auto_resume_on_start = False
    try:
        for index in range(20):
            key = f'RJ{index:08d}'
            db.conn.execute('INSERT INTO works(rj_id,status) VALUES(?,?)', (key, 'queued'))
            db.upsert_download(key, key, 'track.wav', str(tmp_path / key), 'queued')
            db.set_metadata_cache(key, key, '', '', {}, [])
        def unexpected(*args, **kwargs):
            raise AssertionError('startup must not load JSON payloads per work')
        db.get_metadata_cache = unexpected
        orc = Orchestrator(NetworkKernel(config), config, db)
        asyncio.run(orc.restore_pending_downloads())
        assert orc.download_queue.empty()
        assert len(db.get_pending_downloads()) == 20
    finally:
        db.close()


def test_queue_aggregates_files_before_joining_large_work_text(tmp_path):
    db = LibraryVault(tmp_path / 'history.db')
    try:
        db.conn.execute('INSERT INTO works(rj_id,title,status) VALUES(?,?,?)',
                        ('RJ00000001', 'long title ' * 1000, 'queued'))
        db.conn.execute('INSERT INTO works(rj_id,title,status) VALUES(?,?,?)',
                        ('RJ00000002', 'empty', 'queued'))
        for index in range(100):
            db.upsert_download(str(index), 'RJ00000001', 'track.wav', 'unused',
                               'queued', index, 100)
        # Files with no works row must remain visible as well.
        db.upsert_download('orphan', 'RJ00000003', 'other.wav', 'unused', 'failed')
        page = DownloadService(db).fetch_queue_page(status_filter='all')
        items = {item.rj_id: item for item in page.items}
        assert items['RJ00000001'].file_count == 100
        assert items['RJ00000001'].downloaded_bytes == sum(range(100))
        assert items['RJ00000002'].file_count == 0
        assert items['RJ00000003'].queue_state == 'failed'
        plan = [str(tuple(row)) for row in db.conn.execute(
            'EXPLAIN QUERY PLAN ' + DownloadService._aggregate_sql())]
        assert not any('TEMP B-TREE FOR GROUP BY' in row for row in plan)
    finally:
        db.close()
