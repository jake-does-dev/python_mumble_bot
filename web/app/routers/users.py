from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from app.auth import create_access_token, get_current_user
from app.services.users import UsersService
from app.models.users import Token, UserCreate
from app.limiter import limiter
from pydantic import BaseModel

router = APIRouter(prefix="/api/users", tags=["users"])

class ChangePassword(BaseModel):
    current_password: str
    new_password: str

@router.post("/login", response_model=Token)
@limiter.limit("5/minute")
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    if not UsersService().authenticate(form_data.username, form_data.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token({"sub": form_data.username})
    return {"access_token": token, "token_type": "bearer"}

@router.post("/register")
def register(user: UserCreate, current_user: str = Depends(get_current_user)):
    users_service = UsersService()
    if not users_service.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Only admins can register new users")
    if not users_service.create_user(user.username, user.password):
        raise HTTPException(status_code=400, detail="Username already exists")
    return {"message": "User created successfully"}

@router.get("/me")
def me(current_user: str = Depends(get_current_user)):
    users_service = UsersService()
    return {"username": current_user, "is_admin": users_service.is_admin(current_user)}

@router.post("/change-password")
def change_password(body: ChangePassword, current_user: str = Depends(get_current_user)):
    users_service = UsersService()
    if not users_service.authenticate(current_user, body.current_password):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    users_service.change_password(current_user, body.new_password)
    return {"message": "Password changed successfully"}