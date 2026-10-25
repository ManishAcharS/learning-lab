from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

app = FastAPI(title="Taskflow API")


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "message": "TaskFlow api is running"
    }


# Tasks live in memory and are reset whenever the API process restarts.
tasks = [
    {"id": 1, "title": "Learn FastAPI", "completed": False},
    {"id": 2, "title": "Build my first API", "completed": False}
]


def _find_task(task_id: int):
    return next((task for task in tasks if task["id"] == task_id), None)


@app.get("/tasks")
def get_tasks():
    return tasks


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    completed: bool = False


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    completed: bool | None = None

    @field_validator("title", "completed")
    @classmethod
    def reject_explicit_null(cls, value):
        # Omitted fields never reach this validator, so partial updates still
        # leave them unchanged. An explicit JSON null, however, is rejected.
        if value is None:
            raise ValueError("must not be null; omit the field to leave it unchanged")
        return value


@app.post("/tasks", status_code=201)
def create_task(task: TaskCreate):
    new_task = {
        "id": max((existing["id"] for existing in tasks), default=0) + 1,
        "title": task.title,
        "completed": task.completed
    }
    tasks.append(new_task)
    return new_task


@app.get("/tasks/{task_id}")
def get_task(task_id: int):
    task = _find_task(task_id)
    if task is not None:
        return task

    raise HTTPException(
        status_code=404,
        detail="Task not found"
    )


@app.patch("/tasks/{task_id}")
def update_task(task_id: int, update: TaskUpdate):
    task = _find_task(task_id)
    if task is not None:
        # Keep omitted fields unchanged during a partial update.
        changes = update.model_dump(exclude_unset=True)
        task.update(changes)
        return task

    raise HTTPException(status_code=404, detail="Task not found")


@app.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int):
    for index, task in enumerate(tasks):
        if task["id"] == task_id:
            tasks.pop(index)
            return

    raise HTTPException(status_code=404, detail="Task not found")

