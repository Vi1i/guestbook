from pydantic import BaseModel, EmailStr


class RequestLinkBody(BaseModel):
    email: EmailStr
    invite_code: str


class RequestLinkResponse(BaseModel):
    message: str = "If that invite code is valid, a login link has been sent."


class TokenErrorResponse(BaseModel):
    detail: str
