from pydantic import BaseModel
from typing import List, Optional

class Clip(BaseModel):
    identifier: str
    name: str
    file: str
    tags: List[str] = []
    is_favourite: bool = False