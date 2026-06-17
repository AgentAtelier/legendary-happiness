from mcp_client import _extract_image_b64


class _Block:
    def __init__(self, text=None, data=None):
        if text is not None:
            self.text = text
        if data is not None:
            self.data = data


def test_extract_image_from_image_block():
    content = [_Block(text='{"format":"png"}'), _Block(data="ABC123")]
    assert _extract_image_b64(content) == "ABC123"


def test_extract_image_none_when_absent():
    assert _extract_image_b64([_Block(text='{"format":"png"}')]) is None


def test_extract_image_empty_content():
    assert _extract_image_b64([]) is None
    assert _extract_image_b64(None) is None
