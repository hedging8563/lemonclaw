from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path

from lemonclaw.agent.context import ContextBuilder
from lemonclaw.agent.tools.filesystem import ReadAttachmentTool


def _make_workspace(tmp_path: Path) -> Path:
    (tmp_path / 'skills').mkdir(exist_ok=True)
    (tmp_path / 'memory').mkdir(exist_ok=True)
    (tmp_path / 'sessions').mkdir(exist_ok=True)
    return tmp_path


def _write_minimal_xlsx(path: Path) -> None:
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr(
            '[Content_Types].xml',
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
            '</Types>',
        )
        zf.writestr(
            '_rels/.rels',
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>',
        )
        zf.writestr(
            'xl/workbook.xml',
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        zf.writestr(
            'xl/_rels/workbook.xml.rels',
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
            '</Relationships>',
        )
        zf.writestr(
            'xl/sharedStrings.xml',
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="2" uniqueCount="2">'
            '<si><t>Name</t></si><si><t>Alice</t></si></sst>',
        )
        zf.writestr(
            'xl/worksheets/sheet1.xml',
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><v>42</v></c></row>'
            '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2"><v>7</v></c></row>'
            '</sheetData></worksheet>',
        )


def _write_minimal_docx(path: Path) -> None:
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr(
            '[Content_Types].xml',
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>',
        )
        zf.writestr(
            '_rels/.rels',
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>',
        )
        zf.writestr(
            'word/document.xml',
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body>'
            '<w:p><w:r><w:t>Hello DOCX</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Second paragraph.</w:t></w:r></w:p>'
            '</w:body></w:document>',
        )




def test_context_builder_includes_attachment_inventory_and_triggers_xlsx(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)
    spreadsheet = workspace / 'budget.xlsx'
    _write_minimal_xlsx(spreadsheet)

    messages = builder.build_messages(history=[], current_message='看下这个表格', media=[str(spreadsheet)], channel='webui', chat_id='webui')

    assert 'xlsx' in builder._triggered_skills
    user_content = messages[-1]['content']
    assert isinstance(user_content, str)
    assert '[Attached files]' in user_content
    assert 'budget.xlsx' in user_content
    assert 'read_attachment' in user_content


def test_read_file_rejects_image_attachments(tmp_path: Path) -> None:
    from lemonclaw.agent.tools.filesystem import ReadFileTool

    workspace = _make_workspace(tmp_path)
    image = workspace / 'scan.jpg'
    image.write_bytes(b'fake-jpeg-bytes')

    tool = ReadFileTool(workspace=workspace)
    output = asyncio.run(tool.execute(path=str(image)))

    assert 'image attachment' in output
    assert 'analyze_image' in output


def test_read_attachment_rejects_image_attachments(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    image = workspace / 'scan.jpg'
    image.write_bytes(b'fake-jpeg-bytes')

    tool = ReadAttachmentTool(workspace=workspace)
    output = asyncio.run(tool.execute(path=str(image)))

    assert 'image attachment' in output
    assert 'analyze_image' in output


def test_analyze_image_uses_vision_model(tmp_path: Path) -> None:
    from lemonclaw.agent.tools.filesystem import AnalyzeImageTool
    from lemonclaw.providers.base import LLMResponse

    class DummyProvider:
        def __init__(self):
            self.calls = []

        async def chat(self, **kwargs):
            self.calls.append(kwargs)
            return LLMResponse(content='识别出的文字')

    workspace = _make_workspace(tmp_path)
    image = workspace / 'scan.jpg'
    image.write_bytes(b'fake-jpeg-bytes')
    provider = DummyProvider()
    tool = AnalyzeImageTool(provider=provider, workspace=workspace)

    output = asyncio.run(tool.execute(path=str(image), instruction='提取图片文字'))

    assert output == '识别出的文字'
    assert provider.calls
    assert provider.calls[0]['model'] == 'gpt-4.1-mini'
    content = provider.calls[0]['messages'][1]['content']
    assert isinstance(content, list)
    assert any(item.get('type') == 'image_url' for item in content if isinstance(item, dict))


def test_read_attachment_supports_xlsx_and_zip(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    spreadsheet = workspace / 'report.xlsx'
    _write_minimal_xlsx(spreadsheet)
    archive = workspace / 'bundle.zip'
    with zipfile.ZipFile(archive, 'w') as zf:
        zf.writestr('docs/readme.txt', 'hello')
        zf.writestr('data/numbers.csv', 'a,b\n1,2\n')

    tool = ReadAttachmentTool(workspace=workspace)
    xlsx_output = asyncio.run(tool.execute(path=str(spreadsheet)))
    zip_output = asyncio.run(tool.execute(path=str(archive)))

    assert '[Sheet] Sheet1' in xlsx_output
    assert 'Name | 42' in xlsx_output
    assert 'Alice | 7' in xlsx_output
    assert 'docs/readme.txt' in zip_output
    assert 'data/numbers.csv' in zip_output


def test_agent_loop_persists_webui_media_into_session_attachment_dir(make_agent_loop, tmp_path: Path) -> None:
    loop, _bus = make_agent_loop()
    upload = tmp_path / 'upload.csv'
    upload.write_text('name,score\nAlice,9\n', encoding='utf-8')

    asyncio.run(loop.process_direct(
        '分析这个文件',
        session_key='webui:test-upload',
        channel='webui',
        chat_id='webui',
        media=[str(upload)],
    ))

    session = loop.sessions.get_or_create('webui:test-upload')
    stored_media = session.messages[0]['media'][0]['path']
    assert stored_media.startswith(str(loop.sessions.get_attachment_dir('webui:test-upload')))
    assert Path(stored_media).is_file()
    history = session.get_history()
    assert '[Attached files]' in history[0]['content']
    assert 'upload.csv' in history[0]['content']


def test_agent_loop_rewrites_inbound_attachment_paths_for_im_sessions(make_agent_loop, tmp_path: Path) -> None:
    loop, _bus = make_agent_loop()
    source = tmp_path / 'report.xlsx'
    _write_minimal_xlsx(source)

    original_content = f'[file: {source} (report.xlsx)]\n请读取这个文档'
    asyncio.run(loop.process_direct(
        original_content,
        session_key='telegram:123',
        channel='telegram',
        chat_id='123',
        media=[str(source)],
    ))

    session = loop.sessions.get_or_create('telegram:123')
    user_message = session.messages[0]
    persisted_path = user_message['media'][0]['path']
    assert persisted_path.startswith(str(loop.sessions.get_attachment_dir('telegram:123')))
    assert persisted_path in user_message['content']
    assert str(source) not in user_message['content']


def test_read_attachment_supports_pdf_and_docx(tmp_path: Path, monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    from lemonclaw.utils.attachments import inspect_attachment

    workspace = _make_workspace(tmp_path)
    document = workspace / 'notes.docx'
    _write_minimal_docx(document)
    pdf = workspace / 'paper.pdf'
    pdf.write_bytes(b'%PDF-1.4 fake')

    class _FakePage:
        def __init__(self, text: str):
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class _FakeReader:
        def __init__(self, _path: str):
            self.pages = [_FakePage('Hello PDF'), _FakePage('Second PDF page')]

    monkeypatch.setitem(sys.modules, 'pypdf', SimpleNamespace(PdfReader=_FakeReader))

    docx_output = inspect_attachment(str(document))
    pdf_output = inspect_attachment(str(pdf))

    assert 'Document preview:' in docx_output
    assert 'Hello DOCX' in docx_output
    assert 'Second paragraph.' in docx_output
    assert 'PDF preview:' in pdf_output
    assert '[Page 1]' in pdf_output
    assert 'Hello PDF' in pdf_output



def test_archive_session_rewrites_attachment_paths(tmp_path: Path) -> None:
    from lemonclaw.gateway.webui.message_schema import serialize_ui_message
    from lemonclaw.session.manager import SessionManager

    mgr = SessionManager(tmp_path)
    source = tmp_path / 'demo.txt'
    source.write_text('hello', encoding='utf-8')
    media, _mapping = mgr.persist_attachments('webui:test-archive', [str(source)])
    original_persisted_path = media[0]
    session = mgr.get_or_create('webui:test-archive')
    session.messages.append(serialize_ui_message({
        'role': 'assistant',
        'content': f'[file: {media[0]} (demo.txt)]',
        'media': media,
    }, session_key='webui:test-archive'))
    mgr.save(session)

    assert mgr.archive_session('webui:test-archive') is True

    archived = next(item for item in mgr.list_sessions() if item['key'].startswith('webui:test-archive:'))
    archived_session = mgr.get_or_create(archived['key'])
    message = archived_session.messages[0]
    archived_path = message['media'][0]['path']
    assert archived_path.startswith(str(mgr.get_attachment_dir(archived['key'])))
    assert archived_path in message['content']
    assert original_persisted_path not in message['content']
    assert Path(archived_path).is_file()

