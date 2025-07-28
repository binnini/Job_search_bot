from fastapi import FastAPI
from typing import List
from db.io import read_recruitOut
from db.models import RecruitOut

app = FastAPI()

@app.get("/recruits", response_model=List[RecruitOut])
def get_recruits(limit: int = 300000):
    # return "안녕"
    return read_recruitOut(limit)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server.api_server:app", host="0.0.0.0", port=9000, reload=True)