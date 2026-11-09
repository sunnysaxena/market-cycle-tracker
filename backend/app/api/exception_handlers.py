from fastapi import Request
from fastapi.responses import JSONResponse

from fastapi import Request
from fastapi.responses import JSONResponse

from app.schemas.common import APIErrorDetail, APIErrorResponse
from app.services.api_errors import APIServiceError


async def api_service_exception_handler(
    request: Request,
    exc: APIServiceError,
) -> JSONResponse:
    """Convert API service exceptions into consistent responses."""

    response = APIErrorResponse(
        error=APIErrorDetail(
            code=exc.error_code,
            message=str(exc),
        )
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=response.model_dump(),
    )

