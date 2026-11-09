import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.exception_handlers import api_service_exception_handler
from app.api.v1.batches import router as batches_router
from app.core.database import get_db
from app.services.api_errors import APIServiceError
from app.services.batch_service import NoCompletedBatchError


class TestBatchesAPI(unittest.TestCase):

    def setUp(self):
        self.db = object()

        self.app = FastAPI()
        self.app.include_router(
            batches_router,
            prefix="/api/v1",
        )
        self.app.add_exception_handler(
            APIServiceError,
            api_service_exception_handler,
        )

        def override_get_db():
            yield self.db

        self.app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.app.dependency_overrides.clear()

    @staticmethod
    def make_batch(
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

    def test_default_query_parameters(self):
        batches = [self.make_batch()]

        with patch(
            "app.api.v1.batches.list_import_batches",
            return_value=(batches, 1),
        ) as service_mock:

            response = self.client.get("/api/v1/batches")

        self.assertEqual(response.status_code, 200)

        service_mock.assert_called_once_with(
            self.db,
            completed_only=True,
            limit=50,
            offset=0,
        )

    def test_query_parameters_are_forwarded_to_service(self):
        batches = [
            self.make_batch(5),
            self.make_batch(4),
        ]

        with patch(
            "app.api.v1.batches.list_import_batches",
            return_value=(batches, 10),
        ) as service_mock:

            response = self.client.get(
                "/api/v1/batches",
                params={
                    "completed_only": "false",
                    "limit": 2,
                    "offset": 4,
                },
            )

        self.assertEqual(response.status_code, 200)

        service_mock.assert_called_once_with(
            self.db,
            completed_only=False,
            limit=2,
            offset=4,
        )

    def test_response_contains_batch_records_and_pagination(self):
        batches = [
            self.make_batch(5),
            self.make_batch(4),
        ]

        with patch(
            "app.api.v1.batches.list_import_batches",
            return_value=(batches, 10),
        ):
            response = self.client.get(
                "/api/v1/batches",
                params={
                    "limit": 2,
                    "offset": 4,
                },
            )

        self.assertEqual(response.status_code, 200)

        data = response.json()

        self.assertEqual(len(data["batches"]), 2)
        self.assertEqual(data["batches"][0]["id"], 5)
        self.assertEqual(data["batches"][0]["status"], "completed")
        self.assertEqual(data["batches"][0]["imported_rows"], 22609)
        self.assertIsNotNone(data["batches"][0]["imported_at_utc"])

        self.assertEqual(data["pagination"]["limit"], 2)
        self.assertEqual(data["pagination"]["offset"], 4)
        self.assertEqual(data["pagination"]["returned_count"], 2)
        self.assertEqual(data["pagination"]["total_records"], 10)

        self.assertNotIn("source_path", data["batches"][0])
        self.assertNotIn("source_sha256", data["batches"][0])
        self.assertNotIn("source_size_bytes", data["batches"][0])

    def test_empty_batch_list_response(self):
        with patch(
            "app.api.v1.batches.list_import_batches",
            return_value=([], 0),
        ):
            response = self.client.get("/api/v1/batches")

        self.assertEqual(response.status_code, 200)

        data = response.json()

        self.assertEqual(data["batches"], [])
        self.assertEqual(data["pagination"]["returned_count"], 0)
        self.assertEqual(data["pagination"]["total_records"], 0)

    def test_limit_must_be_within_allowed_range(self):
        for limit in (0, 201):
            with self.subTest(limit=limit):
                response = self.client.get(
                    "/api/v1/batches",
                    params={"limit": limit},
                )

                self.assertEqual(response.status_code, 422)

    def test_offset_cannot_be_negative(self):
        response = self.client.get(
            "/api/v1/batches",
            params={"offset": -1},
        )

        self.assertEqual(response.status_code, 422)

    def test_invalid_completed_only_value_is_rejected(self):
        response = self.client.get(
            "/api/v1/batches",
            params={"completed_only": "invalid"},
        )

        self.assertEqual(response.status_code, 422)

    def test_service_error_uses_standard_error_response(self):
        with patch(
            "app.api.v1.batches.list_import_batches",
            side_effect=NoCompletedBatchError(
                "No completed historical import batch is available."
            ),
        ):
            response = self.client.get("/api/v1/batches")

        self.assertEqual(response.status_code, 409)

        data = response.json()

        self.assertIn("error", data)
        self.assertEqual(
            data["error"]["code"],
            "NO_COMPLETED_BATCH",
        )
        self.assertEqual(
            data["error"]["message"],
            "No completed historical import batch is available.",
        )


if __name__ == "__main__":
    unittest.main()
