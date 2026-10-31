from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from pymongo import ReturnDocument

from app.db import get_db
from app.ratelimit import rate_limit

router = APIRouter(prefix="/todo", tags=["todo"], dependencies=[Depends(rate_limit)])


class TodoIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    done: bool = False


class Todo(TodoIn):
    id: str


def _oid(todo_id: str) -> ObjectId:
    try:
        return ObjectId(todo_id)
    except InvalidId:
        raise HTTPException(status_code=404, detail="Todo not found")


def _out(doc: dict) -> Todo:
    return Todo(id=str(doc["_id"]), title=doc["title"], done=doc["done"])


@router.get("", response_model=list[Todo])
async def list_todos() -> list[Todo]:
    return [_out(d) async for d in get_db().todos.find()]


@router.post("", response_model=Todo, status_code=status.HTTP_201_CREATED)
async def create_todo(body: TodoIn) -> Todo:
    result = await get_db().todos.insert_one(body.model_dump())
    return Todo(id=str(result.inserted_id), **body.model_dump())


@router.get("/{todo_id}", response_model=Todo)
async def get_todo(todo_id: str) -> Todo:
    doc = await get_db().todos.find_one({"_id": _oid(todo_id)})
    if doc is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    return _out(doc)


@router.put("/{todo_id}", response_model=Todo)
async def update_todo(todo_id: str, body: TodoIn) -> Todo:
    doc = await get_db().todos.find_one_and_update(
        {"_id": _oid(todo_id)},
        {"$set": body.model_dump()},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    return _out(doc)


@router.delete("/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_todo(todo_id: str) -> None:
    result = await get_db().todos.delete_one({"_id": _oid(todo_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Todo not found")
