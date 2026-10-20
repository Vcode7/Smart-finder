import os

# torch and FAISS each bundle an OpenMP runtime; without this Windows aborts with OMP Error #15
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import uvicorn
from app.core.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.ENVIRONMENT == "development",
        workers=1,
    )
