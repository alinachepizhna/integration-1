import os
from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, conlist

BATCH_MAX_ITEMS = int(os.getenv("BATCH_MAX_ITEMS", "50"))

class OrderCreate(BaseModel):
    client_name: str = Field(..., min_length=2, max_length=120)
    gr_liv_area: float = Field(..., gt=0, le=10000)
    total_bsmt_sf: float = Field(..., ge=0, le=10000)
    garage_area: float = Field(..., ge=0, le=2000)
    year_built: int = Field(..., ge=1872, le=2010)
    overall_qual: int = Field(..., ge=1, le=10)
    ms_zoning: str = Field(..., min_length=1, max_length=10)

class OrderUpdate(BaseModel):
    client_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    gr_liv_area: Optional[float] = Field(default=None, gt=0, le=10000)
    total_bsmt_sf: Optional[float] = Field(default=None, ge=0, le=10000)
    garage_area: Optional[float] = Field(default=None, ge=0, le=2000)
    year_built: Optional[int] = Field(default=None, ge=1872, le=2010)
    overall_qual: Optional[int] = Field(default=None, ge=1, le=10)
    ms_zoning: Optional[str] = Field(default=None, min_length=1, max_length=10)

class OrderRead(BaseModel):
    id: int
    client_name: str
    gr_liv_area: float
    total_bsmt_sf: float
    garage_area: float
    year_built: int
    overall_qual: int
    ms_zoning: str
    predicted_price: Optional[float] = None
    status: str
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

class BatchOrderRequest(BaseModel):
    orders: List[OrderCreate] = Field(..., min_length=1, max_length=BATCH_MAX_ITEMS)

class BatchOrderItemResult(BaseModel):
    index: int
    order_id: int
    status: Literal["priced", "failed"]
    predicted_price: Optional[float] = None
    error: Optional[str] = None

class BatchOrderResponse(BaseModel):
    total: int
    results: List[BatchOrderItemResult]