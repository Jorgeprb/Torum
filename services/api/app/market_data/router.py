from fastapi import APIRouter, Request

from app.market_data.mock import MockMarketService, MockMarketStatus

router = APIRouter(prefix="/mock-market", tags=["mock-market"])


def get_mock_market(request: Request) -> MockMarketService:
    return request.app.state.mock_market


@router.post("/start", response_model=MockMarketStatus)
async def start_mock_market(request: Request) -> MockMarketStatus:
    return await get_mock_market(request).start()


@router.post("/stop", response_model=MockMarketStatus)
async def stop_mock_market(request: Request) -> MockMarketStatus:
    return await get_mock_market(request).stop()


@router.get("/status", response_model=MockMarketStatus)
def mock_market_status(request: Request) -> MockMarketStatus:
    return get_mock_market(request).status()
