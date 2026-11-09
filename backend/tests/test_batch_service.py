import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.batch_service import (
    BatchNotCompletedError,
    BatchNotFoundError,
    NoCompletedBatchError,
    list_import_batches,
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


class TestBatchListingService(unittest.TestCase):

    def setUp(self):
        self.db = MagicMock()

    def configure_query_results(self, batches, total_records):
        count_result = MagicMock()
        count_result.scalar_one.return_value = total_records

        records_result = MagicMock()
        records_result.scalars.return_value.all.return_value = batches

        self.db.execute.side_effect = [
            count_result,
            records_result,
        ]

    def make_batch(self, batch_id, status="completed"):
        return SimpleNamespace(
            id=batch_id,
            status=status,
            imported_rows=22609,
            imported_at_utc=datetime(
                2026, 11, 1, 13, 38, 45, tzinfo=timezone.utc
            ),
        )

    def test_lists_completed_batches_by_default(self):
        expected = [
            self.make_batch(5),
            self.make_batch(4),
        ]
        self.configure_query_results(expected, total_records=2)

        records, total = list_import_batches(self.db)

        self.assertEqual(records, expected)
        self.assertEqual(total, 2)
        self.assertEqual(self.db.execute.call_count, 2)

    def test_applies_limit_and_offset(self):
        expected = [self.make_batch(3)]
        self.configure_query_results(expected, total_records=10)

        records, total = list_import_batches(
            self.db,
            limit=2,
            offset=4,
        )

        self.assertEqual(records, expected)
        self.assertEqual(total, 10)

        records_statement = self.db.execute.call_args_list[1].args[0]
        compiled_sql = str(records_statement)

        self.assertIn("LIMIT", compiled_sql.upper())
        self.assertIn("OFFSET", compiled_sql.upper())

    def test_can_include_non_completed_batches(self):
        expected = [
            self.make_batch(5),
            self.make_batch(4, status="processing"),
        ]
        self.configure_query_results(expected, total_records=2)

        records, total = list_import_batches(
            self.db,
            completed_only=False,
        )

        self.assertEqual(records, expected)
        self.assertEqual(total, 2)

        count_statement = self.db.execute.call_args_list[0].args[0]
        compiled_sql = str(count_statement)

        self.assertNotIn("WHERE", compiled_sql.upper())

    def test_returns_empty_list_when_no_batches_match(self):
        self.configure_query_results([], total_records=0)

        records, total = list_import_batches(self.db)

        self.assertEqual(records, [])
        self.assertEqual(total, 0)

    def test_rejects_invalid_completed_only(self):
        with self.assertRaises(ValueError):
            list_import_batches(
                self.db,
                completed_only=1,
            )

        self.db.execute.assert_not_called()

    def test_rejects_invalid_limits(self):
        for limit in (0, -1, 201, True, "50", 5.5):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    list_import_batches(
                        self.db,
                        limit=limit,
                    )

        self.db.execute.assert_not_called()

    def test_rejects_invalid_offsets(self):
        for offset in (-1, True, "5", 5.5):
            with self.subTest(offset=offset):
                with self.assertRaises(ValueError):
                    list_import_batches(
                        self.db,
                        offset=offset,
                    )

        self.db.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
