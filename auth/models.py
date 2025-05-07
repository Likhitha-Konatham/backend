from pydantic import BaseModel, EmailStr, conint, Field, root_validator, ValidationError, validator
from fastapi import HTTPException, status
from typing import Optional
from datetime import datetime,time,timedelta

class UserSchema(BaseModel):
    firstname: str
    lastname: str
    email: EmailStr
    password: str
    name: str = Field(default="", alias='name')  # Adding the name field
    requested_at: datetime = Field(default_factory=datetime.now)

    @validator("name", pre=True, always=True)
    def set_name(cls, v, values):
        return f"{values['firstname']} {values['lastname']}".strip()

class UserLoginSchema(BaseModel):
    email: Optional[EmailStr] = None
    password: str

    @root_validator(pre=True)
    def check_email_or_mobile(cls, values):
        # Ensure that either email is provided
        if not values.get('email'):
            raise ValueError("Email must be provided.")
        return values
