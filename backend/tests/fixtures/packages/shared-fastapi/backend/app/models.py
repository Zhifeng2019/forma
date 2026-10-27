from pydantic import BaseModel, Field


class ItemInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)
