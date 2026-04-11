from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from typing import Optional


class Settings(BaseSettings):
    SERVICE_NAME: Optional[str] = "verification-service"
    API_PREFIX: str = "/api"
    PORT: Optional[int] = 3006
    ENVIRONMENT: Optional[str] = "development"

    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DB: str = "pycrest"

    JWT_SECRET: str = "CHANGE_ME"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24
    ACCESS_TOKEN_EXPIRE_MINUTES: Optional[int] = 60

    IDEMPOTENCY_ENABLED: bool = True
    IDEMPOTENCY_TTL_HOURS: int = 24

    DEFAULT_IFSC: str = "PCIN01001"
    INTERNAL_SERVICE_TOKEN: str = "CHANGE_ME"
    UPLOAD_BASE_PATH: str = "./uploads"

    LOAN_SERVICE_URL: Optional[str] = None
    AUTH_SERVICE_URL: Optional[str] = None
    EMI_SERVICE_URL: Optional[str] = None
    WALLET_SERVICE_URL: Optional[str] = None
    PAYMENT_SERVICE_URL: Optional[str] = None
    VERIFICATION_SERVICE_URL: Optional[str] = None
    ADMIN_SERVICE_URL: Optional[str] = None
    MANAGER_SERVICE_URL: Optional[str] = None

    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="allow"
    )


settings = Settings()