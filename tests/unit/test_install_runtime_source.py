from pathlib import Path

import pytest
from scripts.install import ENVIRONMENTS, RUNTIME_DISTRIBUTIONS, _runtime_distributions


@pytest.mark.parametrize(
    ("environment_name", "expected_adapters"),
    [
        ("wiki-agent", ("langchain",)),
        ("mail-agent", ("agentframework",)),
        ("dev", ("agentframework", "langchain")),
        ("wiki-mcp-reference", ()),
    ],
)
def test_runtime_source_includes_only_environment_adapters(
    tmp_path: Path,
    environment_name: str,
    expected_adapters: tuple[str, ...],
) -> None:
    distribution_names = (*RUNTIME_DISTRIBUTIONS, "agentframework", "langchain")
    package_root = tmp_path / "packages" / "python"
    for name in distribution_names:
        project = package_root / name
        project.mkdir(parents=True)
        (project / "pyproject.toml").touch()

    result = _runtime_distributions(tmp_path, ENVIRONMENTS[environment_name])

    assert tuple(path.name for path in result) == (*RUNTIME_DISTRIBUTIONS, *expected_adapters)
