import pytest

from conn.lab.private_exec import parse_request


def test_private_exec_request_is_bounded_and_exact() -> None:
    request = parse_request(
        '{"schema_version":1,"command":["/usr/bin/true"],'
        '"environment":{"OPENAI_API_KEY":"secret"}}'
    )

    assert request.command == ("/usr/bin/true",)
    assert request.environment == {"OPENAI_API_KEY": "secret"}

    with pytest.raises(ValueError, match="private request"):
        parse_request('{"schema_version":1,"command":["/usr/bin/true"],"extra":1}')
    with pytest.raises(ValueError, match="private environment"):
        parse_request(
            '{"schema_version":1,"command":["/usr/bin/true"],'
            '"environment":{"CONN_SERVER_PORT":"8787"}}'
        )
