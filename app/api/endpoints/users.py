"""
Users API endpoint — illustrates patterns: Pydantic schemas,
dependency injection, async handlers, error handling.
"""
from typing import List
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr

router = APIRouter()


# --- Schemas ---
class UserCreate(BaseModel):
    name: str
    email: EmailStr


class UserRead(BaseModel):
    id: int
    name: str
    email: str

    model_config = {"from_attributes": True}


# --- Fake in-memory store (replace with real DB service) ---
_DB: dict[int, dict] = {}
_SEQ = 0


# --- Endpoints ---
@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate):
    global _SEQ
    _SEQ += 1
    user = {"id": _SEQ, "name": payload.name, "email": payload.email}
    _DB[_SEQ] = user
    return user


@router.get("/", response_model=List[UserRead])
async def list_users():
    return list(_DB.values())


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: int):
    user = _DB.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int):
    if user_id not in _DB:
        raise HTTPException(status_code=404, detail="User not found")
    del _DB[user_id]
