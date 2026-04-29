"""
Test 02 — Inbox Navigation
--------------------------
Verifies that after login we can navigate to the คณบดีคณะวิศวกรรมศาสตร์ inbox,
list documents from หนังสือเข้าภายนอก and หนังสือเข้าภายใน, and that none of
the returned items are tagged "ส่งต่อ".

This test will FAIL with NotImplementedError until inbox navigation selectors
are mapped in edoc_client.get_inbox_items(). After running test_01 first,
inspect the screenshots to find the correct selectors, then implement the method.

Run:
    pytest tests/test_02_inbox.py -v
    HEADLESS=false pytest tests/test_02_inbox.py -v   # watch in browser
"""
import pytest
from tests.conftest import HEADLESS
from src.edoc_client import EdocClient, EXCLUDE_TAG, TARGET_SUB_INBOXES


@pytest.mark.asyncio
async def test_inbox_external_lists_documents(edoc_secrets):
    """หนังสือเข้าภายนอก should return a list (possibly empty if no new docs)."""
    async with EdocClient(headless=HEADLESS) as client:
        await client.login(edoc_secrets["EDOC_USERNAME"], edoc_secrets["EDOC_PASSWORD"])
        docs = await client.get_inbox_items("หนังสือเข้าภายนอก")

    assert isinstance(docs, list), "get_inbox_items() must return a list"
    print(f"\nFound {len(docs)} documents in หนังสือเข้าภายนอก")
    for doc in docs:
        print(f"  [{doc.doc_id}] {doc.subject} — {doc.from_org} ({doc.date})")


@pytest.mark.asyncio
async def test_inbox_internal_lists_documents(edoc_secrets):
    """หนังสือเข้าภายใน should return a list (possibly empty if no new docs)."""
    async with EdocClient(headless=HEADLESS) as client:
        await client.login(edoc_secrets["EDOC_USERNAME"], edoc_secrets["EDOC_PASSWORD"])
        docs = await client.get_inbox_items("หนังสือเข้าภายใน")

    assert isinstance(docs, list)
    print(f"\nFound {len(docs)} documents in หนังสือเข้าภายใน")


@pytest.mark.asyncio
async def test_inbox_excludes_forwarded_tag(edoc_secrets):
    """No returned document should have the 'ส่งต่อ' tag."""
    async with EdocClient(headless=HEADLESS) as client:
        await client.login(edoc_secrets["EDOC_USERNAME"], edoc_secrets["EDOC_PASSWORD"])
        all_docs = []
        for sub_inbox in TARGET_SUB_INBOXES:
            all_docs.extend(await client.get_inbox_items(sub_inbox))

    forwarded = [d for d in all_docs if EXCLUDE_TAG in d.tags]
    assert not forwarded, (
        f"Documents with tag '{EXCLUDE_TAG}' should be excluded but got: "
        + ", ".join(d.doc_id for d in forwarded)
    )
