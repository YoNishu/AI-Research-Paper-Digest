from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Azure OpenAI (AI Foundry)
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = "gpt-4o"
    azure_openai_api_version: str = "2024-12-01-preview"

    # Database
    database_url: str = "postgresql+asyncpg://localhost:5432/paper_digest"

    # Azure Blob Storage
    azure_blob_connection_string: str = ""
    azure_storage_account_name: str = ""
    azure_blob_container_name: str = "paper-pdfs"

    # Scheduler
    poll_interval_hours: int = 6

    # Categories seed file
    categories_file: str = "categories.yaml"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
