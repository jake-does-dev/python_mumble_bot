from pydantic import BaseModel

class PlayCommand(BaseModel):
    clip_ref: str
    requested_by: str