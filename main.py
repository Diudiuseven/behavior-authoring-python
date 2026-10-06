import uvicorn

from app.api import app  # noqa: F401  (uvicorn entrypoint: main:app)

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000)
