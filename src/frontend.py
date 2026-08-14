import os

from observatory.app import app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("FRONTEND_HOST", "127.0.0.1"),
        port=int(os.getenv("FRONTEND_PORT", "8000")),
    )
