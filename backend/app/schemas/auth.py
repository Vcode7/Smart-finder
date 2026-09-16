from pydantic import BaseModel, EmailStr
from typing import Optional

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserSignup(BaseModel):
    email: EmailStr
    username: str
    password: str

class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    role: str

class AuthResponse(BaseModel):
    user: UserResponse
