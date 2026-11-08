"""Rotas de /tasks. Dados guardados em memória (somem ao reiniciar)."""

from fastapi import APIRouter, HTTPException, Response, status

from app.schemas import Task, TaskCreate, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])

# "Banco de dados" em memória: {id: Task}
_tasks: dict[int, Task] = {}
_next_id = 1


def _get_or_404(task_id: int) -> Task:
    task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return task


@router.get("", response_model=list[Task], operation_id="listTasks")
def list_tasks() -> list[Task]:
    return list(_tasks.values())


@router.post("", response_model=Task, status_code=status.HTTP_201_CREATED, operation_id="createTask")
def create_task(data: TaskCreate) -> Task:
    global _next_id
    task = Task(id=_next_id, title=data.title, done=False)
    _tasks[task.id] = task
    _next_id += 1
    return task


@router.get("/{id}", response_model=Task, operation_id="getTask")
def get_task(id: int) -> Task:
    return _get_or_404(id)


@router.put("/{id}", response_model=Task, operation_id="updateTask")
def update_task(id: int, data: TaskUpdate) -> Task:
    task = _get_or_404(id)
    updated = task.model_copy(update=data.model_dump(exclude_unset=True, exclude_none=True))
    _tasks[id] = updated
    return updated


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteTask")
def delete_task(id: int) -> Response:
    _get_or_404(id)
    del _tasks[id]
    return Response(status_code=status.HTTP_204_NO_CONTENT)
