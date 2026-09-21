import asyncio
import logging
from typing import Any, Optional
import aiohttp
from centrifuge import (
    Client,
    ClientEventHandler,
    ConnectedContext,
    DisconnectedContext,
    ErrorContext,
    PublicationContext,
    SubscribedContext,
    SubscriptionErrorContext,
    SubscriptionEventHandler,
    SubscribingContext,
    UnsubscribedContext,
)
from config import LIS_WS_URL, LIS_WS_TOKEN_URL, LIS_CHANNEL, LIS_SKINS_API_KEY
from analyzer.metrics import process_item
from shared_state import record_event

logger = logging.getLogger(__name__)

# Queue for item processing (protection against event avalanche / thundering herd)
ITEM_QUEUE: asyncio.Queue = asyncio.Queue(maxsize=5000)

# Set of already processed IDs (deduplication)
# NOTE: Currently unused in the code. See architectural notes below.
seen_ids: set[str] = set()


async def get_ws_token(session: aiohttp.ClientSession) -> Optional[str]:
    """Retrieves a temporary token for WebSocket connection."""
    async with session.get(
        LIS_WS_TOKEN_URL,
        headers={
            "Authorization": f"Bearer {LIS_SKINS_API_KEY}",
            "Accept": "application/json",
        },
    ) as resp:
        text = await resp.text()
        if resp.status != 200:
            logger.error(f"Auth error {resp.status}: {text[:200]}")
            return None
        data = await resp.json()
        token = data.get("token")
        if not token and isinstance(data.get("data"), dict):
            token = data["data"].get("token")
        return token


def extract_item(payload: Any) -> Optional[dict]:
    """
    Extracts the item from the WebSocket payload in various formats:
    - {"item": {...}}
    - {"data": {"item": {...}}}
    - {"data": {...}}
    - plain {...}
    """
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("item"), dict):
        return payload["item"]
    if "id" in payload:
        return payload
    nested_data = payload.get("data")
    if isinstance(nested_data, dict):
        if isinstance(nested_data.get("item"), dict):
            return nested_data["item"]
        if "id" in nested_data:
            return nested_data
    return None


async def item_worker() -> None:
    """Sequentially processes items from the queue."""
    while True:
        item = await ITEM_QUEUE.get()
        try:
            await process_item(item)
        except Exception:
            logger.exception("Error in item_worker")
        finally:
            ITEM_QUEUE.task_done()


class ClientEvents(ClientEventHandler):
    """Centrifuge client event handler."""
    async def on_connected(self, ctx: ConnectedContext) -> None:
        logger.info("Centrifuge connected")

    async def on_disconnected(self, ctx: DisconnectedContext) -> None:
        logger.warning(f"Centrifuge disconnected: {ctx}")

    async def on_error(self, ctx: ErrorContext) -> None:
        logger.error(f"Centrifuge client error: {ctx}")


class SubscriptionEvents(SubscriptionEventHandler):
    """Channel subscription event handler."""
    async def on_subscribing(self, ctx: SubscribingContext) -> None:
        logger.info(f"Subscribing to {LIS_CHANNEL}")

    async def on_subscribed(self, ctx: SubscribedContext) -> None:
        logger.info(f"Subscribed to {LIS_CHANNEL}")

    async def on_unsubscribed(self, ctx: UnsubscribedContext) -> None:
        logger.warning(f"Unsubscribed from {LIS_CHANNEL}: {ctx}")

    async def on_error(self, ctx: SubscriptionErrorContext) -> None:
        logger.error(f"Subscription error for {LIS_CHANNEL}: {ctx}")

    async def on_publication(self, ctx: PublicationContext) -> None:
        # Record delay between events (for bot statistics)
        record_event()
        payload = ctx.pub.data
        item = extract_item(payload)
        if item is None:
            logger.debug(f"Unrecognized item: {str(payload)[:300]}")
            return
        try:
            ITEM_QUEUE.put_nowait(item)
        except asyncio.QueueFull:
            logger.error(f"ITEM_QUEUE full; dropping item id={item.get('id')}")


async def websocket_loop() -> None:
    """Main WebSocket connection loop."""
    worker_task = asyncio.create_task(item_worker())
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async def get_client_token() -> str:
            token = await get_ws_token(session)
            if not token:
                raise RuntimeError("Failed to obtain websocket token")
            return token

        client = Client(
            LIS_WS_URL,
            events=ClientEvents(),
            get_token=get_client_token,
            use_protobuf=False,
        )
        subscription = client.new_subscription(
            LIS_CHANNEL,
            events=SubscriptionEvents(),
        )
        try:
            logger.info(f"Connecting to Centrifuge: {LIS_WS_URL}")
            await client.connect()
            await subscription.subscribe()
            logger.info(f"WebSocket listener started: channel={LIS_CHANNEL}")
            # The client maintains the connection automatically
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            logger.info("WebSocket loop cancelled")
            raise
        except Exception:
            logger.exception("Centrifuge loop failed")
            raise
        finally:
            worker_task.cancel()
            await asyncio.gather(worker_task, return_exceptions=True)
            try:
                await client.disconnect()
            except Exception:
                logger.debug("Client disconnect failed", exc_info=True)


async def lis_skins_websocket_loop() -> None:
    """Infinite loop with connection retry attempts (exponential backoff)."""
    backoff = 1.0
    max_backoff = 30.0
    while True:
        try:
            await websocket_loop()
        except asyncio.CancelledError:
            logger.info("Main loop cancelled")
            raise
        except Exception:
            logger.exception("WebSocket crashed; reconnect in %.1f seconds", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
        else:
            backoff = 1.0