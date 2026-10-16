from fastapi import APIRouter, HTTPException

from app.db import db

router = APIRouter(prefix="/products", tags=["products"])


@router.get("")
async def list_products():
    return {"items": list(db.products.find({}, {"_id": 0}).sort("name", 1).limit(500))}


@router.get("/{product_id}")
async def get_product(product_id: str):
    product = db.products.find_one({"product_id": product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"product": product}
