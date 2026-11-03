import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, List
from .auth import router as auth_router, get_current_user

# Підключення роутера для логіну
import httpx
from fastapi import BackgroundTasks, Body, Depends, FastAPI, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from . import crud, models, schemas
from .database import SessionLocal, engine, get_db


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orders_api")

FORECAST_URL = os.getenv("FORECAST_URL", "http://forecast-api:8001/predict")
FORECAST_TIMEOUT = float(os.getenv("FORECAST_TIMEOUT", "3.0"))
BATCH_MAX_ITEMS = int(os.getenv("BATCH_MAX_ITEMS", "50"))

FEATURE_FIELDS = {
    "gr_liv_area",
    "total_bsmt_sf",
    "garage_area",
    "year_built",
    "overall_qual",
    "ms_zoning",
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Спільний екземпляр httpx.AsyncClient на час роботи застосунку
    app.state.http_client = httpx.AsyncClient(timeout=FORECAST_TIMEOUT)
    yield
    await app.state.http_client.aclose()

app = FastAPI(title="Orders API", lifespan=lifespan)
app.include_router(auth_router)

async def request_forecast(client: httpx.AsyncClient, payload: dict) -> float:
    response = await client.post(FORECAST_URL, json=payload, timeout=FORECAST_TIMEOUT)
    response.raise_for_status()
    return float(response.json()["predicted_price"])


async def process_order_forecast(order_id: int) -> None:
    """Фонове завдання (BackgroundTasks): відкриває власну сесію БД та HTTP-клієнт."""
    ts = datetime.now(timezone.utc).isoformat()
    db = SessionLocal()
    try:
        order = db.query(models.Order).filter(models.Order.id == order_id).first()
        if not order:
            logger.warning(f"[{ts}] order_id={order_id} result=skipped_deleted (order was deleted before processing)")
            return

        payload = {
            "gr_liv_area": order.gr_liv_area,
            "total_bsmt_sf": order.total_bsmt_sf,
            "garage_area": order.garage_area,
            "year_built": order.year_built,
            "overall_qual": order.overall_qual,
            "ms_zoning": order.ms_zoning,
        }

        try:
            async with httpx.AsyncClient(timeout=FORECAST_TIMEOUT) as client:
                price = await request_forecast(client, payload)
            # Перевіряємо ще раз перед комітом, чи не видалили замовлення під час HTTP-запиту
            db.refresh(order)
            order.predicted_price = price
            order.status = "priced"
            db.commit()
            ts_done = datetime.now(timezone.utc).isoformat()
            logger.info(f"[{ts_done}] order_id={order_id} result=priced predicted_price={price}")
        except Exception as exc:
            order.predicted_price = None
            order.status = "failed"
            db.commit()
            ts_err = datetime.now(timezone.utc).isoformat()
            logger.error(f"[{ts_err}] order_id={order_id} result=failed error={type(exc).__name__}: {exc}")
    finally:
        db.close()


# --- ЗАВДАННЯ 2: Відкладене створення замовлення (202 Accepted) ---
@app.post("/orders", response_model=schemas.OrderRead, status_code=status.HTTP_202_ACCEPTED)
def create_order(
    payload: schemas.OrderCreate,
    background_tasks: BackgroundTasks,
    response: Response,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),  # вимога автентифікації
):
    order = models.Order(
        **payload.model_dump(),
        predicted_price=None,
        status="pending",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    # Додаємо заголовок Location
    response.headers["Location"] = f"/orders/{order.id}"

    # Запускаємо відкладене обчислення прогнозу після повернення HTTP-відповіді
    background_tasks.add_task(process_order_forecast, order.id)
    return order


# --- ЗАВДАННЯ 1: Паралельна пакетна обробка (POST /orders/batch) ---
@app.post("/orders/batch", response_model=schemas.BatchOrderResponse)
async def create_orders_batch(
    items: Annotated[List[schemas.OrderCreate], Body(min_length=1, max_length=BATCH_MAX_ITEMS)],
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),  # збереження вимоги автентифікації
):
    # 1. Створюємо всі замовлення у БД зі статусом pending
    created_orders: List[models.Order] = []
    for item in items:
        order = models.Order(**item.model_dump(), predicted_price=None, status="pending")
        db.add(order)
        created_orders.append(order)
    db.commit()
    for order in created_orders:
        db.refresh(order)

    # 2. Формуємо корутини для конкурентного виклику Forecast API через спільний AsyncClient
    http_client: httpx.AsyncClient = request.app.state.http_client

    async def fetch_one(order_obj: models.Order):
        payload = {
            "gr_liv_area": order_obj.gr_liv_area,
            "total_bsmt_sf": order_obj.total_bsmt_sf,
            "garage_area": order_obj.garage_area,
            "year_built": order_obj.year_built,
            "overall_qual": order_obj.overall_qual,
            "ms_zoning": order_obj.ms_zoning,
        }
        return await request_forecast(http_client, payload)

    # Виконуємо всі запити ПАРАЛЕЛЬНО (конкурентно)
    raw_results = await asyncio.gather(
        *(fetch_one(o) for o in created_orders),
        return_exceptions=True,
    )

    # 3. Оновлюємо замовлення результатами і формуємо відповідь
    batch_results: List[schemas.BatchOrderItemResult] = []
    for idx, (order, res) in enumerate(zip(created_orders, raw_results)):
        if isinstance(res, Exception):
            order.status = "failed"
            order.predicted_price = None
            batch_results.append(
                schemas.BatchOrderItemResult(
                    index=idx,
                    order_id=order.id,
                    status="failed",
                    error="ForecastUnavailable",
                )
            )
        else:
            order.status = "priced"
            order.predicted_price = res
            batch_results.append(
                schemas.BatchOrderItemResult(
                    index=idx,
                    order_id=order.id,
                    status="priced",
                    predicted_price=res,
                )
            )
    db.commit()

    return schemas.BatchOrderResponse(total=len(batch_results), results=batch_results)


# --- ЗАВДАННЯ 3: Оновлення замовлення (PATCH /orders/{oid}) з відкладеним перерахунком ---
@app.patch("/orders/{oid}", response_model=schemas.OrderRead)
def update_order(
    oid: int,
    payload: schemas.OrderUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    order = db.query(models.Order).filter(models.Order.id == oid).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    update_data = payload.model_dump(exclude_unset=True)
    features_changed = bool(FEATURE_FIELDS.intersection(update_data.keys()))

    for field, value in update_data.items():
        setattr(order, field, value)

    if features_changed:
        # Очищуємо попередній прогноз, ставимо pending і запускаємо фонову задачу
        order.status = "pending"
        order.predicted_price = None
        db.commit()
        db.refresh(order)
        background_tasks.add_task(process_order_forecast, order.id)
    else:
        # Змінилися лише дані клієнта — прогноз не перераховуємо
        db.commit()
        db.refresh(order)

    return order


# Додатковий службовий ендпоінт для перевірки ідемпотентності (Завдання 4, п. 4)
@app.post("/orders/{oid}/recalculate", response_model=schemas.OrderRead, status_code=status.HTTP_202_ACCEPTED)
def recalculate_order(
    oid: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    order = db.query(models.Order).filter(models.Order.id == oid).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    background_tasks.add_task(process_order_forecast, order.id)
    return order

@app.get("/orders/{oid}", response_model=schemas.OrderRead)
def get_order(
    oid: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    order = db.query(models.Order).filter(models.Order.id == oid).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order