import pytest
from src.config import Config
from src.memory_cleaner import clean_all_memory

@pytest.fixture(scope="function", autouse=True)
def clean_memory_after_test():
    """Autouse fixture to clean VRAM and system memory after every single test."""
    yield
    try:
        config = Config()
        clean_all_memory(config, unload_models=False)
    except Exception:
        pass
