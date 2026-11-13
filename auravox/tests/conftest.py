import pytest

from auravox.studio import Studio


@pytest.fixture
def studio(tmp_path):
    return Studio(tmp_path / "home")
