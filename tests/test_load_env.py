import sys
import os

# Ensure project root is on sys.path so tests can import the package
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mxdc.utils.misc import load_env


def test_load_env_parsing(tmp_path, monkeypatch):
    content = """# comment line
API_KEY="abc=123"
DEBUG=true
EMPTY=
NAME="O'Reilly"
ESCAPED="line\\nnext"
export SECRET="s3cr3t"
BARE_VAR
"""

    p = tmp_path / ".env"
    p.write_text(content)

    # pre-existing env var should not be overwritten by load_env
    monkeypatch.setenv('DEBUG', 'already')

    result = load_env(p)

    assert result['API_KEY'] == 'abc=123'
    assert result['DEBUG'] == 'true'
    assert result['EMPTY'] == ''
    assert result['NAME'] == "O'Reilly"
    assert result['ESCAPED'] == 'line\nnext'
    assert result['SECRET'] == 's3cr3t'
    assert result['BARE_VAR'] == ''

    # os.environ should not have been overwritten for DEBUG
    assert os.environ.get('DEBUG') == 'already'
    # but SECRET/API_KEY should be present
    assert os.environ.get('SECRET') == 's3cr3t'
    assert os.environ.get('API_KEY') == 'abc=123'


def test_load_env_missing_file(tmp_path):
    p = tmp_path / '.env_missing'
    # file does not exist
    result = load_env(p)
    assert result == {}

