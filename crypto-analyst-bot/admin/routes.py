from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets, os
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from database.engine import get_db_session
from database import operations as db_ops
from database.models import Purchase
from sqlalchemy.future import select

router = APIRouter(prefix="/admin", tags=["admin"])

security = HTTPBasic()

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    username = os.getenv("ADMIN_USER", "admin")
    password = os.getenv("ADMIN_PASS", "admin")
    correct_username = secrets.compare_digest(credentials.username, username)
    correct_password = secrets.compare_digest(credentials.password, password)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True

# --- User management ---
@router.get("/users/{user_id}")
async def get_user_details(user_id: int, authorized: bool = Depends(verify_credentials), db: AsyncSession = Depends(get_db_session)):
    user = await db_ops.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    stats = await db_ops.get_user_stats(db, user_id)
    sub = await db_ops.get_subscription(db, user_id)
    result = await db.execute(select(Purchase).filter(Purchase.user_id == user_id))
    purchases = [p.product_id for p in result.scalars().all()]
    return {
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "stars_balance": user.stars_balance,
        "subscription_active": sub.is_active if sub else False,
        "stats": stats,
        "purchases": purchases,
    }

@router.post("/users/{user_id}/subscription")
async def set_subscription(user_id: int, active: bool, authorized: bool = Depends(verify_credentials), db: AsyncSession = Depends(get_db_session)):
    sub = await db_ops.create_or_update_subscription(db, user_id, is_active=active)
    return {"user_id": user_id, "active": sub.is_active}

# --- Products management ---
@router.post("/products")
async def create_product(
    name: str,
    description: str,
    stars_price: int,
    item_type: str,
    file: UploadFile = File(...),
    authorized: bool = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db_session),
):
    content_path = os.path.join("uploads", file.filename)
    os.makedirs("uploads", exist_ok=True)
    with open(content_path, "wb") as f:
        f.write(await file.read())
    product = await db_ops.create_product(
        db,
        name=name,
        description=description,
        item_type=item_type,
        stars_price=stars_price,
        content_type="file",
        content_value=content_path,
    )
    return {"id": product.id}


# --- Courses management ---
@router.post("/courses")
async def create_course(
    title: str,
    description: str,
    stars_price: int,
    content_type: str,
    file_id: Optional[str] = None,
    authorized: bool = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db_session),
):
    course = await db_ops.create_course(
        db,
        title=title,
        description=description,
        stars_price=stars_price,
        content_type=content_type,
        file_id=file_id,
    )
    return {"id": course.id}


# --- Feedback management ---
@router.get("/feedback")
async def list_feedback(
    limit: int = 100,
    authorized: bool = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db_session),
):
    messages = await db_ops.get_feedback_messages(db, limit)
    return [
        {
            "user_id": m.user_id,
            "text": m.message_text,
            "timestamp": m.timestamp.isoformat(),
        }
        for m in messages
    ]
