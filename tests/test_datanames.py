import pytest
from mxdc.utils import datatools


@pytest.fixture(scope="session")
def setup_manager():
    manager = datatools.NameManager(database={'test': 3, 'lysozyme': 0, 'thaumatin': 1})
    return manager

@pytest.mark.parametrize(
    "manager,sample,expected,description",
    [
        ("setup_manager", "thermolysin", "thermolysin", "Non-existing name"),
        ("setup_manager", "lysozyme", "lysozyme-1", "Existing name with 0 entries"),
        ("setup_manager", "test", "test-4", "Existing name with 3 entries"),
        ("setup_manager", "thaumatin", "thaumatin-2", "Existing name with 1 entry"),
    ],
)
def test_names(manager, sample, expected, description, request):
    manager = request.getfixturevalue(manager)
    name = manager.get(sample)
    assert name == expected, f'{description}: {name=} != {sample=}'


def test_fixes(setup_manager):
    sample = 'insulin'
    names = ['insulin', 'insulin-1', 'insulin-8', 'insulin', 'insul']
    expected = ['insulin', 'insulin-1', 'insulin-8', 'insulin-9', 'insul']
    fixed = setup_manager.fix(sample, *names)
    assert fixed == expected, f'Fixed names do not match expected {fixed=} != {expected=}'