from lemonclaw.gateway.webui.message_schema import serialize_ui_message


def test_serialize_ui_message_hides_assistant_tool_prelude_markdown():
    payload = serialize_ui_message(
        {
            "role": "assistant",
            "content": "我先检查一下文件。",
            "tool_calls": [
                {
                    "id": "call_1",
                    "state": "done",
                    "detail": "read_file(\"notes.md\")",
                }
            ],
        }
    )

    assert payload["content"] == "我先检查一下文件。"
    assert any(block["type"] == "tool" for block in payload["blocks"])
    assert not any(block["type"] == "markdown" for block in payload["blocks"])
