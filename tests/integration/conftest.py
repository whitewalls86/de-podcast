import os
from pathlib import Path

import pytest


def _load_dotenv() -> None:
    env_file = Path(__file__).parent.parent.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


_load_dotenv()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests against a live Docker Compose stack",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
    if config.getoption("--integration"):
        return
    skip = pytest.mark.skip(reason="pass --integration to run against live stack")
    for item in items:
        if item.get_closest_marker("integration"):
            item.add_marker(skip)
