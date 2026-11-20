from fastapi import APIRouter, HTTPException, status

from app.dependencies import StoreDep, UserId
from app.schemas import OrderCreate, OrderResponse, ProductResponse, utc_now

router = APIRouter(tags=["Ürünler ve siparişler"])

PRODUCTS = (
    ProductResponse(
        id="starter-kit",
        name="Demo başlangıç paketi",
        description="Demo kataloğu için örnek ürün.",
        price=19.90,
    ),
    ProductResponse(
        id="consultation",
        name="Örnek danışmanlık",
        description="Gerçek hizmet veya randevu değildir.",
        price=49.00,
    ),
)


@router.get("/products", response_model=list[ProductResponse])
def list_products() -> list[ProductResponse]:
    return list(PRODUCTS)


@router.post("/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate, user_id: UserId, store: StoreDep) -> dict:
    products = {product.id: product for product in PRODUCTS}
    total = 0.0
    for item in payload.items:
        product = products.get(item.product_id)
        if product is None:
            raise HTTPException(
                status_code=422, detail=f"Bilinmeyen ürün kimliği: {item.product_id}"
            )
        total += product.price * item.quantity
    return store.create(
        "orders",
        user_id,
        {
            **payload.model_dump(),
            "total": round(total, 2),
            "status": "pending",
            "created_at": utc_now(),
        },
    )


@router.get("/orders", response_model=list[OrderResponse])
def list_orders(user_id: UserId, store: StoreDep) -> list[dict]:
    return store.list("orders", user_id)
