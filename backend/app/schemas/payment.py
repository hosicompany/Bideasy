from pydantic import BaseModel

ALLOWED_AMOUNTS = [5000, 10000, 30000, 50000]


class CreateOrderRequest(BaseModel):
    amount: int  # ALLOWED_AMOUNTS 중 하나


class CreateOrderResponse(BaseModel):
    order_id: str
    amount: int
    order_name: str
    customer_name: str
    toss_client_key: str
