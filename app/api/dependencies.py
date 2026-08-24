from fastapi import Header, HTTPException

async def get_token_header(authorization: str = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid or missing Authorization header")
    return authorization.split(" ")[1]
