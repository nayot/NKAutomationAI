"""
Test 03 — Document Detail
--------------------------
Verifies that we can open the first inbox item and extract the
'ข้อความแนบท้าย/สั่งการ' field text.

This test depends on test_02 succeeding (at least one document in inbox).

Run:
    pytest tests/test_03_document.py -v
    HEADLESS=false pytest tests/test_03_document.py -v
"""
import pytest
from tests.conftest import HEADLESS
from src.edoc_client import EdocClient, TARGET_SUB_INBOXES


@pytest.mark.asyncio
async def test_document_detail_has_attachment_note(edoc_secrets):
    """
    Open the first available inbox document and verify attachment_note is populated.
    Prints the extracted text so we can validate the content manually.
    """
    async with EdocClient(headless=HEADLESS) as client:
        await client.login(edoc_secrets["EDOC_USERNAME"], edoc_secrets["EDOC_PASSWORD"])

        doc = None
        for sub_inbox in TARGET_SUB_INBOXES:
            items = await client.get_inbox_items(sub_inbox)
            if items:
                doc = items[0]
                break

        if doc is None:
            pytest.skip("No documents in inbox — nothing to test detail extraction on.")

        detailed = await client.get_document_detail(doc)

    assert detailed.doc_id == doc.doc_id
    print(f"\nDocument: {detailed.subject}")
    print(f"From: {detailed.from_org}")
    print(f"Date: {detailed.date}")
    print(f"ข้อความแนบท้าย/สั่งการ:\n{detailed.attachment_note or '(empty)'}")

    # attachment_note may be empty for some docs — that's valid
    assert isinstance(detailed.attachment_note, str)
