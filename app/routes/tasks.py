"""Rotas de /tasks. Dados guardados no DynamoDB."""

import uuid

from fastapi import APIRouter, HTTPException, Response, status

from app.database import get_table
from app.schemas import Task, TaskCreate, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _get_or_404(task_id: str) -> Task:
    item = get_table().get_item(Key={"id": task_id}).get("Item")
    if item is None:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return Task(**item)


@router.get("", response_model=list[Task], operation_id="listTasks")
def list_tasks() -> list[Task]:
    # scan lê a tabela inteira: ok para estudo, caro em tabelas grandes
    items = get_table().scan()["Items"]
    return [Task(**item) for item in items]


@router.post("", response_model=Task, status_code=status.HTTP_201_CREATED, operation_id="createTask")
def create_task(data: TaskCreate) -> Task:
    task = Task(id=str(uuid.uuid4()), title=data.title, done=False)
    get_table().put_item(Item=task.model_dump())
    return task


@router.get("/{id}", response_model=Task, operation_id="getTask")
def get_task(id: str) -> Task:
    return _get_or_404(id)


@router.put("/{id}", response_model=Task, operation_id="updateTask")
def update_task(id: str, data: TaskUpdate) -> Task:
    task = _get_or_404(id)
    updated = task.model_copy(update=data.model_dump(exclude_unset=True, exclude_none=True))
    get_table().put_item(Item=updated.model_dump())
    return updated


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteTask")
def delete_task(id: str) -> Response:
    _get_or_404(id)
    get_table().delete_item(Key={"id": id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
