from fastapi import FastAPI
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
