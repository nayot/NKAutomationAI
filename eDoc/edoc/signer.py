import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime

from edoc.browser import get_inbox_frame, navigate_to_inbox, wait_for_content_frame


@dataclass
class SignResult:
    data_id: str
    title: str
    command: str
    signed: bool      # True if OK clicked, False if Cancel/dry-run/skip
    error: str | None = None


async def _dump_modal_state(page, data_id: str, ts: str) -> None:
    """Snapshot enough of the sign-confirm dialog to diagnose why ยืนยัน didn't dismiss it.
    Writes phase5_modal_stuck_{data_id}_{ts}.html — open it next to the .png to compare
    radio states, hidden inputs, and any inline validation messages."""
    try:
        info = await page.evaluate(
            """
            () => {
                const pick = (el, attrs) => {
                    const out = { tag: el.tagName.toLowerCase() };
                    for (const a of attrs) {
                        const v = el.getAttribute(a);
                        if (v !== null) out[a] = v;
                    }
                    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') {
                        out.value = el.value;
                        if (el.type === 'checkbox' || el.type === 'radio') out.checked = el.checked;
                        out.visible = !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
                    }
                    return out;
                };
                const radios = Array.from(document.querySelectorAll(
                    'input[id^="optSignConfirmOptions"], input[name*="SignConfirmOptions"]'
                )).map(el => pick(el, ['id','name','type','value']));
                const checkboxes = Array.from(document.querySelectorAll(
                    'input[type="checkbox"]'
                )).filter(el => /sign|forward|send|target|note/i.test(el.id + ' ' + (el.name || '')))
                  .map(el => pick(el, ['id','name','type','value']));
                const buttons = Array.from(document.querySelectorAll(
                    '#btnSignConfirmOK, #btnSignConfirmCancel, [id^="btnSignConfirm"]'
                )).map(el => ({
                    id: el.id,
                    visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
                    disabled: el.disabled,
                    onclick: el.getAttribute('onclick'),
                }));
                const containers = [];
                for (const sel of ['#divSignConfirm', '#dialogSignConfirm', '#SignConfirmPanel']) {
                    const el = document.querySelector(sel);
                    if (el) containers.push({ selector: sel, html: el.outerHTML });
                }
                // Fallback: walk up from btnSignConfirmOK to find its panel
                const ok = document.querySelector('#btnSignConfirmOK');
                if (ok && containers.length === 0) {
                    let p = ok;
                    for (let i = 0; i < 6 && p && p.parentElement; i++) p = p.parentElement;
                    if (p) containers.push({ selector: 'ancestor(#btnSignConfirmOK, 6)', html: p.outerHTML });
                }
                const alerts = Array.from(document.querySelectorAll(
                    '.error, .alert, [class*="error"], [class*="alert"], [class*="toast"]'
                )).filter(el => el.offsetWidth || el.offsetHeight)
                  .map(el => ({ class: el.className, text: el.innerText.slice(0, 200) }));
                // Visible form inputs inside the sign-confirm modal — easy scan for
                // which required field is empty when validation rejects the submit.
                const modal = document.querySelector('#divDialogSignConfirmation') || document.body;
                const isVisible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
                const dialogInputs = Array.from(modal.querySelectorAll('input, select, textarea'))
                    .filter(isVisible)
                    .map(el => {
                        const label = el.id ? document.querySelector(`label[for="${el.id}"]`) : null;
                        const out = {
                            tag: el.tagName.toLowerCase(),
                            id: el.id || null,
                            name: el.getAttribute('name') || null,
                            type: el.type || null,
                            label: label ? label.innerText.trim().slice(0, 80) : null,
                        };
                        if (el.type === 'checkbox' || el.type === 'radio') {
                            out.checked = el.checked;
                            out.value = el.value;
                        } else if (el.tagName === 'SELECT') {
                            const opt = el.options[el.selectedIndex];
                            out.value = el.value;
                            out.selectedText = opt ? opt.text.slice(0, 80) : null;
                        } else {
                            out.value = (el.value || '').slice(0, 200);
                        }
                        out.required = el.required || el.getAttribute('aria-required') === 'true';
                        out.disabled = el.disabled;
                        return out;
                    });
                // Any signature pad canvas inside the dialog — a blank one is a common
                // cause of "กรุณากรอกหรือเลือกข้อมูล".
                const signaturePads = Array.from(modal.querySelectorAll('canvas'))
                    .filter(isVisible)
                    .map(c => ({
                        id: (c.closest('[id]') || {}).id || null,
                        width: c.width,
                        height: c.height,
                        // A signature canvas has non-zero pixel data; blank canvases have all-transparent pixels.
                        blank: (() => {
                            try {
                                if (!c.width || !c.height) return true;
                                const ctx = c.getContext('2d');
                                const data = ctx.getImageData(0, 0, c.width, c.height).data;
                                for (let i = 3; i < data.length; i += 4) if (data[i] !== 0) return false;
                                return true;
                            } catch (e) { return null; }
                        })(),
                    }));
                return {
                    url: location.href,
                    radios, checkboxes, buttons, alerts, containers,
                    dialogInputs, signaturePads,
                    targetNote: (document.querySelector('#txtTargetTypeNote') || {}).value || null,
                };
            }
            """
        )
    except Exception as e:
        logging.warning("Could not evaluate modal state for %s: %s", data_id, e)
        return

    out_path = f"screenshots/phase5_modal_stuck_{data_id}_{ts}.html"
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("<!-- modal_stuck dump for " + data_id + " @ " + ts + " -->\n")
            f.write("<pre>\n")
            f.write(json.dumps(
                {k: v for k, v in info.items() if k != "containers"},
                ensure_ascii=False, indent=2,
            ))
            f.write("\n</pre>\n")
            for c in info.get("containers") or []:
                f.write(f"\n<!-- container: {c['selector']} -->\n")
                f.write(c["html"])
                f.write("\n")
        logging.warning("Wrote modal_stuck DOM dump → %s", out_path)
    except Exception as e:
        logging.warning("Failed to write modal_stuck dump %s: %s", out_path, e)


async def _wait_for_doc_content_ready(content_frame, data_id: str, timeout_ms: int = 60000) -> None:
    """Block until iframeContent0 has finished loading its body (including any embedded PDF).

    Failure mode without this: docs with large PDF attachments expose #btnSign before the
    PDF is fully streamed in. Clicking through opens the sign-confirm modal visually, but
    the OK button's postback handler is bound to form state that's still settling — the
    click lands as a no-op and the modal sits there until our outer hidden-wait gives up.

    We can't trust the frame's `load` event alone because PDFs are typically rendered in
    <embed>/<iframe>/<object> tags whose own load doesn't always bubble. Instead, we wait
    for document.readyState === 'complete' AND for Performance API resource count to be
    stable for ~1.5s (proxy for "no more bytes coming in")."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_ms / 1000

    try:
        await content_frame.wait_for_load_state("load", timeout=timeout_ms)
    except Exception as e:
        logging.warning("Content frame load state did not fire for %s: %s", data_id, e)

    stable_for = 1.5
    last_count = -1
    last_change = loop.time()
    while loop.time() < deadline:
        try:
            ready, count = await content_frame.evaluate(
                "() => [document.readyState, performance.getEntriesByType('resource').length]"
            )
        except Exception as e:
            logging.warning("readiness probe failed mid-wait for %s: %s", data_id, e)
            await asyncio.sleep(0.3)
            continue

        now = loop.time()
        if count != last_count:
            last_count = count
            last_change = now
        if ready == "complete" and (now - last_change) >= stable_for:
            logging.info("Content settled for %s (%d resources)", data_id, count)
            return
        await asyncio.sleep(0.25)

    logging.warning(
        "Content frame did not settle within %ds for %s — proceeding anyway",
        timeout_ms // 1000, data_id,
    )


async def _dismiss_leftover_modal(page, data_id: str) -> None:
    """If a sign-confirm modal is still up from a previous doc, cancel it before continuing.
    The modal lives on the main page; HideContentFrame() doesn't touch it."""
    try:
        cancel_btn = await page.query_selector("#btnSignConfirmCancel")
        if not cancel_btn or not await cancel_btn.is_visible():
            return
        logging.warning("Leftover sign-confirm modal detected; cancelling before opening %s", data_id)
        await page.click("#btnSignConfirmCancel")
        await page.wait_for_selector("#btnSignConfirmOK", state="hidden", timeout=5000)
        await page.evaluate("VN.V2.App.Home.Page.HideContentFrame()")
        await asyncio.sleep(1.0)
    except Exception as e:
        logging.warning("Failed to dismiss leftover modal cleanly: %s", e)


async def _click_sign_confirm_ok(page, data_id: str, ts: str) -> None:
    """Click the ยืนยัน input in the ASP.NET sign-confirm dialog.

    A normal Playwright click can miss this legacy input in live mode even when
    dry-run Cancel works. Resolve the element by its stable id first, then use
    DOM click() on the input itself so the page's own onclick/postback handler is
    activated. XPath/value fallbacks are kept for diagnostics and markup drift.
    """
    selectors = [
        "#btnSignConfirmOK",
        "xpath=//*[@id='btnSignConfirmOK']",
        "input[type='button'][value*='ยืนยัน']",
    ]
    last_error: Exception | None = None
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            await locator.wait_for(state="visible", timeout=5000)
            await locator.scroll_into_view_if_needed()
            handle = await locator.element_handle()
            if handle is None:
                continue
            await page.evaluate("(el) => el.click()", handle)
            logging.info("Clicked sign-confirm OK for %s via %s", data_id, selector)
            return
        except Exception as e:
            last_error = e
            logging.warning("Could not click sign-confirm OK via %s for %s: %s", selector, data_id, e)

    await page.screenshot(path=f"screenshots/phase5_no_ok_button_{data_id}_{ts}.png")
    await _dump_modal_state(page, data_id, ts)
    raise RuntimeError(f"Could not click sign-confirm OK for {data_id}: {last_error}")


_VALIDATION_ALERT_FRAGMENTS = ("กรุณากรอก", "กรุณาเลือก", "เลือกข้อมูล")


async def _accept_next_dialog(page, data_id: str, validation_alerts: list[str]) -> None:
    """Auto-accept the JS dialog the OK click triggers. If the dialog is a validation
    alert (eDoc raises `alert('กรุณากรอกหรือเลือกข้อมูล')` when a required field is
    empty), record its message in `validation_alerts` so the caller can fail fast
    instead of waiting 90s for a modal that will never close."""

    async def accept_dialog(dialog) -> None:
        msg = dialog.message or ""
        try:
            logging.info(
                "Accepting dialog while signing %s: type=%s message=%r",
                data_id,
                dialog.type,
                msg,
            )
            if dialog.type == "alert" and any(frag in msg for frag in _VALIDATION_ALERT_FRAGMENTS):
                validation_alerts.append(msg)
            await dialog.accept()
        except Exception as e:
            logging.warning("Failed to accept dialog while signing %s: %s", data_id, e)

    page.once("dialog", lambda dialog: asyncio.create_task(accept_dialog(dialog)))


async def _ensure_easy_reply_checked(page, data_id: str) -> None:
    """Ensure both easy-reply checkboxes are checked before confirming.

    #chkSignConfirmRpyEnabled      — ตอบกลับแบบง่าย
    #chkSignConfirmRpyPreviousMessages — ส่งต่อเอกสารและข้อความแนบท้ายเดิมของบุคคลก่อนหน้าไปยังผู้รับ
    """
    try:
        for cb_id in ("chkSignConfirmRpyEnabled", "chkSignConfirmRpyPreviousMessages"):
            checkbox = page.locator(f"#{cb_id}")
            if await checkbox.count() == 0:
                logging.warning("Checkbox %s not found for %s", cb_id, data_id)
                continue
            if not await checkbox.is_checked():
                await checkbox.click(force=True)
                await asyncio.sleep(0.2)
            # Ensure via JS in case the click was intercepted
            await page.evaluate(
                f"""
                () => {{
                    const cb = document.getElementById('{cb_id}');
                    if (cb && !cb.checked) {{
                        cb.checked = true;
                        cb.dispatchEvent(new Event('change', {{bubbles: true}}));
                    }}
                }}
                """
            )
        state = await page.evaluate(
            """
            () => {
                const enabled = document.getElementById('chkSignConfirmRpyEnabled');
                const prev    = document.getElementById('chkSignConfirmRpyPreviousMessages');
                return {
                    rpyEnabled: enabled ? enabled.checked : null,
                    rpyPrevious: prev ? prev.checked : null,
                };
            }
            """
        )
        logging.info("Easy reply checkbox state for %s: %s", data_id, state)
    except Exception as e:
        logging.warning("Could not ensure easy reply checked for %s: %s", data_id, e)


async def _ensure_receive_number_choice(page, data_id: str) -> None:
    """Some incoming docs open the sign-confirm dialog with the receive-number
    selector (`pnlSignConfirmRcvReceive .ui-receive-number-choice-number`)
    empty — no <option> children, no value — because the originating workflow
    expects the signer to issue a fresh document number. eDoc's client
    validator then raises 'กรุณากรอกหรือเลือกข้อมูล' on OK and aborts the
    postback. We don't want to consume a real running number, so inject
    'ไม่ออกเลข' (value 'N') and select it; this matches the default state of
    docs that sign cleanly and avoids issuing a number we didn't ask for.
    """
    try:
        state = await page.evaluate(
            """
            () => {
                const root = document.getElementById('pnlSignConfirmRcvReceive');
                if (!root) return { found: false };
                const sel = root.querySelector('.ui-receive-number-choice-number');
                if (!sel) return { found: false };
                const hadValue = !!sel.value && sel.options.length > 0;
                if (hadValue) return { found: true, mutated: false, value: sel.value };
                sel.innerHTML = '';
                const opt = document.createElement('option');
                opt.value = 'N';
                opt.text = 'ไม่ออกเลข';
                opt.selected = true;
                sel.appendChild(opt);
                sel.value = 'N';
                sel.dispatchEvent(new Event('change', { bubbles: true }));
                return { found: true, mutated: true, value: sel.value };
            }
            """
        )
        if state.get("mutated"):
            logging.info("Forced receive-number=N for %s (select was empty)", data_id)
        elif state.get("found"):
            logging.debug("Receive-number already set for %s: %s", data_id, state.get("value"))
    except Exception as e:
        logging.warning("Could not adjust receive-number select for %s: %s", data_id, e)


async def open_and_fill_form(page, doc: dict, inbox_name: str) -> dict:
    data_id = doc["data_id"]
    command = doc.get("command") or doc.get("final_command") or ""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    await _dismiss_leftover_modal(page, data_id)

    content_frame = None
    for attempt in range(3):
        if attempt > 0:
            logging.warning("Retry %d — re-navigating to inbox for %s", attempt, data_id)
            await navigate_to_inbox(page, inbox_name)
            await asyncio.sleep(1.5)

        inbox_frame = await get_inbox_frame(page)
        if not inbox_frame:
            logging.warning("Inbox frame not found on attempt %d", attempt + 1)
            await asyncio.sleep(2)
            continue

        await inbox_frame.click(f"a[data-id='{data_id}']", force=True)
        if attempt == 0:
            await page.screenshot(path=f"screenshots/phase5_before_{data_id}_{ts}.png")
        logging.info("Clicked doc link (attempt %d): %s", attempt + 1, doc["title"])

        content_frame = await wait_for_content_frame(page)
        if content_frame:
            break

        logging.warning("Content frame not found on attempt %d — saving debug screenshot", attempt + 1)
        await page.screenshot(path=f"screenshots/phase5_debug_{data_id}_{ts}_attempt{attempt + 1}.png")

    if not content_frame:
        raise RuntimeError(f"Content frame missing for {doc['title']}")

    # Wait for the doc body (PDF included) to finish loading before clicking ลงนาม.
    # Without this, large-PDF docs leave the sign-confirm modal stuck (OK click no-ops).
    await _wait_for_doc_content_ready(content_frame, data_id)

    for sign_attempt in range(3):
        await content_frame.evaluate("document.getElementById('btnSign').click()")
        logging.info("Clicked btnSign (attempt %d): %s", sign_attempt + 1, data_id)
        try:
            await page.wait_for_selector("#optSignConfirmOptions0", state="visible", timeout=8000)
            break
        except Exception:
            if sign_attempt == 2:
                await page.screenshot(path=f"screenshots/phase5_nodialog_{data_id}_{ts}.png")
                raise RuntimeError(f"Sign dialog never appeared for {doc['title']}")
            logging.warning("Sign dialog not visible, retrying btnSign click")

    await page.click("#optSignConfirmOptions0")
    await page.fill("#txtTargetTypeNote", command)
    await _ensure_easy_reply_checked(page, data_id)
    await _ensure_receive_number_choice(page, data_id)
    # page.fill focuses+types but does NOT blur. .NET often runs onchange/onblur
    # handlers that commit state before the postback fires — without this blur,
    # OK lands on a half-initialized form and the modal stays open.
    await page.evaluate(
        "() => { const e = document.getElementById('txtTargetTypeNote');"
        " if (e) { e.dispatchEvent(new Event('change', {bubbles: true})); e.blur(); } }"
    )
    form_screenshot = f"screenshots/phase5_form_{data_id}_{ts}.png"
    await page.screenshot(path=form_screenshot)
    return {"data_id": data_id, "ts": ts, "form_screenshot": form_screenshot}


async def confirm_sign(page, dry_run: bool, data_id: str, ts: str) -> str:
    # Ensure the OK button is in the viewport before clicking — the dialog can be
    # taller than the viewport and the button scrolls out of the clickable area.
    await page.wait_for_selector("#btnSignConfirmOK", state="visible", timeout=5000)
    await page.locator("#btnSignConfirmOK").scroll_into_view_if_needed()

    validation_alerts: list[str] = []

    if dry_run:
        await page.click("#btnSignConfirmCancel")
        action = "DRY_RUN cancelled"
    else:
        # Snapshot the modal exactly as it is about to be submitted. If the click
        # is later rejected by client validation, the `_pre` dump shows which
        # required fields were empty.
        try:
            await _dump_modal_state(page, data_id, f"{ts}_pre")
        except Exception as e:
            logging.warning("Could not capture pre-click modal state for %s: %s", data_id, e)

        await _accept_next_dialog(page, data_id, validation_alerts)
        await _click_sign_confirm_ok(page, data_id, ts)
        action = "Signed"

        # The dialog handler runs in a background task; yield once so any
        # validation alert fired during the click is recorded before we check.
        await asyncio.sleep(0)
        if validation_alerts:
            try:
                await page.screenshot(path=f"screenshots/phase5_validation_failed_{data_id}_{ts}.png")
                await _dump_modal_state(page, data_id, ts)
            except Exception as dump_error:
                logging.warning("Could not capture validation diagnostics for %s: %s", data_id, dump_error)
            # Leave the modal open so the user can inspect the form in the headful
            # browser. Caller will move on to the next doc; this one stays "to sign".
            raise RuntimeError(
                f"Sign-confirm validation rejected {data_id}: {validation_alerts[0]!r}. "
                f"See screenshots/phase5_modal_stuck_{data_id}_{ts}.html for required fields."
            )

    # The modal disappearing is the only reliable "OK was accepted" signal. networkidle
    # is unsafe here — the app keepalive prevents it ever settling on some docs, which
    # silently burns 30s before this wait even starts.
    # Timeout is generous (90s): docs with large PDF attachments take a long time on
    # the server side — the modal stays up until the backend finishes re-saving the
    # signed PDF, and we saw real signs succeed well past 15s on those docs.
    try:
        await page.wait_for_selector("#btnSignConfirmOK", state="hidden", timeout=90000)
    except Exception:
        try:
            await page.screenshot(path=f"screenshots/phase5_modal_stuck_{data_id}_{ts}.png")
            await _dump_modal_state(page, data_id, ts)
        except Exception as dump_error:
            logging.warning("Could not capture modal-stuck diagnostics for %s: %s", data_id, dump_error)
        raise RuntimeError(f"Sign-confirm dialog did not close after {action} for {data_id}")

    after_screenshot = f"screenshots/phase5_after_{data_id}_{ts}.png"
    await page.screenshot(path=after_screenshot)
    logging.info("%s %s", action, data_id)
    await page.evaluate("VN.V2.App.Home.Page.HideContentFrame()")
    await asyncio.sleep(1.5)
    return after_screenshot


async def dismiss_form(page) -> None:
    await page.wait_for_selector("#btnSignConfirmCancel", state="visible", timeout=5000)
    await page.locator("#btnSignConfirmCancel").scroll_into_view_if_needed()
    await page.click("#btnSignConfirmCancel")
    await page.wait_for_selector("#btnSignConfirmOK", state="hidden", timeout=90000)
    await page.evaluate("VN.V2.App.Home.Page.HideContentFrame()")
    await asyncio.sleep(1.5)


async def sign_one(page, doc: dict, inbox_name: str, dry_run: bool) -> SignResult:
    try:
        ctx = await open_and_fill_form(page, doc, inbox_name)
        await confirm_sign(page, dry_run, ctx["data_id"], ctx["ts"])
        return SignResult(
            data_id=doc["data_id"],
            title=doc["title"],
            command=doc.get("command") or doc.get("final_command") or "",
            signed=not dry_run,
        )
    except Exception as e:
        logging.exception("Sign failed for %s", doc.get("data_id"))
        return SignResult(
            data_id=doc.get("data_id", "?"),
            title=doc.get("title", "?"),
            command=doc.get("command") or doc.get("final_command") or "",
            signed=False,
            error=str(e),
        )
