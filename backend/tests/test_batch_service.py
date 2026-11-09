import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.batch_service import (
    BatchNotCompletedError,
    BatchNotFoundError,
    NoCompletedBatchError,
    resolve_import_batch,
)


class TestBatchResolutionService(unittest.TestCase):

    def setUp(self):
        self.db = MagicMock()

    def make_batch(
        self,
        batch_id=5,
        status="completed",
        imported_rows=22609,
    ):
        return SimpleNamespace(
            id=batch_id,
            status=status,
            imported_rows=imported_rows,
            imported_at_utc=datetime(
                2026, 11, 1, 13, 38, 45, tzinfo=timezone.utc
            ),
        )

    def test_resolves_latest_completed_batch_by_default(self):
        expected = self.make_batch(batch_id=5)

        self.db.execute.return_value.scalar_one_or_none.return_value = (
            expected
        )

        result = resolve_import_batch(self.db)

        self.assertIs(result, expected)
        self.db.execute.assert_called_once()
        self.db.get.assert_not_called()

    def test_resolves_explicit_completed_batch(self):
        expected = self.make_batch(batch_id=4)
        self.db.get.return_value = expected

        result = resolve_import_batch(
            self.db,
            import_batch_id=4,
        )

        self.assertIs(result, expected)
        self.db.get.assert_called_once()

    def test_rejects_unknown_explicit_batch(self):
        self.db.get.return_value = None

        with self.assertRaises(BatchNotFoundError):
            resolve_import_batch(
                self.db,
                import_batch_id=999,
            )

    def test_rejects_non_completed_explicit_batch(self):
        self.db.get.return_value = self.make_batch(
            batch_id=4,
            status="processing",
        )

        with self.assertRaises(BatchNotCompletedError):
            resolve_import_batch(
                self.db,
                import_batch_id=4,
            )

    def test_rejects_when_no_completed_batch_exists(self):
        self.db.execute.return_value.scalar_one_or_none.return_value = None

        with self.assertRaises(NoCompletedBatchError):
            resolve_import_batch(self.db)

    def test_rejects_invalid_batch_ids(self):
        for batch_id in (0, -1, True, "5", 5.5):
            with self.subTest(batch_id=batch_id):
                with self.assertRaises(ValueError):
                    resolve_import_batch(
                        self.db,
                        import_batch_id=batch_id,
                    )

    def test_accepts_completed_status_case_insensitively(self):
        expected = self.make_batch(
            batch_id=5,
            status="COMPLETED",
        )
        self.db.get.return_value = expected

        result = resolve_import_batch(
            self.db,
            import_batch_id=5,
        )

        self.assertIs(result, expected)

    def test_does_not_query_latest_batch_for_explicit_selection(self):
        expected = self.make_batch(batch_id=3)
        self.db.get.return_value = expected

        resolve_import_batch(
            self.db,
            import_batch_id=3,
        )

        self.db.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
