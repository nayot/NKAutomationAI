"""
Test 06 — Order Submission (Dry Run)
--------------------------------------
Verifies that submit_order() navigates to the document, fills the order field,
and takes a screenshot — WITHOUT actually submitting the form (--dry-run mode).

Run:
    pytest tests/test_06_submit.py -v
    HEADLESS=false pytest tests/test_06_submit.py -v
"""
import pytest
from tests.conftest import HEADLESS
from src.edoc_client import EdocClient, TARGET_SUB_INBOXES, SCREENSHOT_DIR


@pytest.mark.asyncio
async def test_submit_order_dry_run(edoc_secrets):
    """
    Opens the first inbox document, fills the order field with
    'ทราบ / ดำเนินการตามเสนอ', takes a screenshot, but does NOT submit.
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
            pytest.skip("No documents in inbox — nothing to test submission on.")

        # dry_run=True: fills but does not submit
        result = await client.submit_order(doc, "ทราบ / ดำเนินการตามเสนอ", dry_run=True)

    # In dry_run mode, we expect True (filled successfully) or a screenshot was saved
    screenshot = SCREENSHOT_DIR / "submit_dry_run.png"
    assert screenshot.exists(), f"Expected dry-run screenshot at {screenshot}"
    print(f"\nDry-run screenshot saved to {screenshot}")
    print("Inspect this screenshot to verify the correct field is filled.")
