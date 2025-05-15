from fastapi import HTTPException, status

class AppExceptionBase(HTTPException):
    def __init__(self, status_code: int, detail: str, error_code: str):
        super().__init__(status_code=status_code, detail=detail)
        self.error_code = error_code

class NotFoundError(AppExceptionBase):
    def __init__(self, detail: str = "Resource not found", error_code: str = "NOT_FOUND"):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail, error_code=error_code)

class DuplicateResourceError(AppExceptionBase):
    def __init__(self, detail: str = "Resource already exists", error_code: str = "DUPLICATE_RESOURCE"):
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail, error_code=error_code)

class AuthError(AppExceptionBase):
    def __init__(self, detail: str = "Authentication failed", error_code: str = "AUTH_FAILED"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            error_code=error_code,
            headers={"WWW-Authenticate": "Bearer"}, # For JWT
        )

class ForbiddenError(AppExceptionBase):
    def __init__(self, detail: str = "Operation forbidden", error_code: str = "FORBIDDEN"):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail, error_code=error_code)

class PaymentRequiredError(AppExceptionBase):
    def __init__(self, detail: str = "Payment required", error_code: str = "PAYMENT_REQUIRED"):
        super().__init__(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=detail, error_code=error_code)

class PaymentError(AppExceptionBase):
    def __init__(self, detail: str = "Payment processing error", error_code: str = "PAYMENT_ERROR", status_code: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(status_code=status_code, detail=detail, error_code=error_code)

class InvalidInputError(AppExceptionBase):
    def __init__(self, detail: str = "Invalid input provided", error_code: str = "INVALID_INPUT"):
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail, error_code=error_code)

class AppLogicError(AppExceptionBase):
    def __init__(self, detail: str = "Application logic error", error_code: str = "APP_LOGIC_ERROR", status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR):
        super().__init__(status_code=status_code, detail=detail, error_code=error_code)

class APIError(AppExceptionBase): # For external API call failures
    def __init__(self, detail: str = "External API error", error_code: str = "EXTERNAL_API_ERROR", status_code: int = status.HTTP_502_BAD_GATEWAY):
        super().__init__(status_code=status_code, detail=detail, error_code=error_code)