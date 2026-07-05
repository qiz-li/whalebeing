from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    searoutes_api_key: str = ""
    database_url: str = "postgresql://postgres:postgres@localhost:5432/whalebeing"
    use_local_ais: bool = True

    class Config:
        env_file = ".env"


settings = Settings()
