from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

app = FastAPI()

# Giao diện dashboard: hiển thị từ thư mục "frontend"
app.mount("/dashboard", StaticFiles(directory="frontend", html=True), name="dashboard")

@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    return FileResponse(os.path.join("frontend", "index.html"))
