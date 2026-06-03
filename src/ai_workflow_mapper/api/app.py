"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .models import ApiError
from .router import JobNotFoundError, router


def create_app() -> FastAPI:
    app = FastAPI(title="AI Workflow Mapper API", version="0.1.0")
    app.include_router(router)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=ApiError(
                error_code="invalid_request",
                message=str(exc),
                retryable=False,
                trace_id="unknown",
            ).model_dump(exclude_none=True),
        )

    @app.exception_handler(JobNotFoundError)
    async def not_found_handler(request, exc: JobNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=ApiError(
                error_code="job_not_found",
                message=str(exc),
                retryable=False,
                trace_id=exc.job_id,
            ).model_dump(exclude_none=True),
        )

    return app


app = create_app()
