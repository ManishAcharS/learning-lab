from fastapi import FastAPI
app = FastAPI(title="Taskflow API")
@app.get("/health")
def health():
    return{
        "status" : "healthy",
        "message" : "TaskFlow api is running"
    }
