from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def root():
    return {"service": "frontend", "message": "Welcome to frontend!"}

@app.get("/hello")
def hello():
    return {"service": "frontend", "message": "Hello from frontend!"}