import argparse
import asyncio
import http

import service
import contract
import uvicorn

from loguru import logger as log
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse


CONFIG_PATH = 'config.env'
CHART_PATH_PREFIX = 'charts'

HOST: str
PORT: int

charts_service = service.Service()


def prepare_static_serve():
    flag = argparse.ArgumentParser()

    flag.add_argument('-host', '--host', type=str, required=True)
    flag.add_argument('-port', '--port', type=int, required=True)
    try:
        args, _ = flag.parse_known_args()
        global HOST, PORT
        HOST = args.host
        PORT = args.port

    except Exception as ex:
        raise Exception(f"parse flags failed: {str(ex)}")


def prepare_service():
    charts_service.load_config(CONFIG_PATH)
    try:
        charts_service.update_stocks_cache()
    except Exception as ex:
        raise Exception(f"update stocks cache failed: {ex}")


async def shutdown_service():
    log.info("service shutting down")
    await asyncio.sleep(0)


async def startup_service():
    try:
        prepare_static_serve()
        prepare_service()
        await asyncio.sleep(0)

    except Exception as ex:
        log.error(f"prepare service failed: {str(ex)}")
        return


app = FastAPI(title="Chart service")
app.mount("/charts", StaticFiles(directory="charts"), name="charts")


@app.get("/health")
async def health() -> contract.HealthResponse:
    await asyncio.sleep(0)
    return contract.HealthResponse(success=True)


@app.post("/chart/{ticker_id}")
async def create_chart(ticker_id: str, req: contract.ChartRequest) -> contract.ChartResponse:
    if ticker_id == "":
        raise HTTPException(
            status_code=http.HTTPStatus.BAD_REQUEST,
            detail="ticker id must be specified",
        )
    if req is None:
        raise HTTPException(
            status_code=http.HTTPStatus.BAD_REQUEST,
            detail="request body not found",
        )

    chart_path = charts_service.create_chart(ticker_id, req.from_date, req.to_date, req.indicators, req.force_refresh)
    formed_chart_url = f"http://{HOST}:{PORT}/{chart_path}"

    return contract.ChartResponse(
        success=True,
        chart_url=formed_chart_url,
    )


public_routes = [
    "/health",
    "/charts/"
]


@app.middleware("http")
async def auth_middleware(req: Request, call_next):
    req_route = req.url.path

    if True in map(lambda public_route: req_route.startswith(public_route), public_routes):
        return await call_next(req)

    check_success: bool = False
    check_status_code: int = http.HTTPStatus.OK
    check_message: str = ""

    auth_token = req.headers.get('X-Auth-Token')
    try:
        charts_service.check_client(auth_token)
        check_success = True

    except service.UnauthorizedException as ex:
        check_status_code = http.HTTPStatus.UNAUTHORIZED
        check_message = str(ex)

    except service.ForbiddenException as ex:
        check_status_code = http.HTTPStatus.FORBIDDEN
        check_message = str(ex)

    except Exception as ex:
        log.error(f"auth middleware failed: {ex}")
        check_status_code = http.HTTPStatus.INTERNAL_SERVER_ERROR
        check_message = 'internal server error'

    if not check_success:
        return JSONResponse(
            status_code=check_status_code,
            content={
                "message": check_message,
            },
        )
    return await call_next(req)


@app.on_event("startup")
async def app_startup():
    try:
        await startup_service()
    except Exception as ex:
        log.error(ex)


@app.on_event("shutdown")
async def add_shutdown():
    await shutdown_service()


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
