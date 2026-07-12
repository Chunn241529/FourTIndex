import pytest
from src.config import Config
from src.memory_cleaner import clean_all_memory

@pytest.fixture(scope="session", autouse=True)
def clean_memory_after_test():
    """Release local model resources once after the test session."""
    yield
    try:
        config = Config()
        clean_all_memory(config, unload_models=False)
    except Exception:
        pass
