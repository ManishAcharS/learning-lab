from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Taskflow API")

@app.get("/health")
def health():
    return{
        "status" : "healthy",
        "message" : "TaskFlow api is running"
    }

tasks = [
    {"id": 1, "title": "Learn FastAPI", "completed": False},
    {"id": 2, "title": "Build my first API", "completed": False}
]

@app.get("/tasks")
def get_tasks():
    return tasks

class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    completed: bool = False

class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    completed: bool | None = None

@app.post("/tasks", status_code=201)
def create_task(task : TaskCreate):
    new_task = {
        "id": len(tasks) + 1,
        "title": task.title,
        "completed": task.completed
    }
    tasks.append(new_task)
    return new_task

@app.get("/tasks/{task_id}")
def get_task(task_id: int):
    for task in tasks:
        if task["id"] == task_id:
            return task

    raise HTTPException(
        status_code=404,
        detail="Task not found"
    )

@app.patch("/tasks/{task_id}")
def update_task(task_id: int, update: TaskUpdate):
    for task in tasks:
        if task["id"] == task_id:
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
