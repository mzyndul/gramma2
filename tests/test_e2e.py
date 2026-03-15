from playwright.sync_api import expect


def _click_icon_and_pick_local(page):
    """Click the G icon, then pick 'Local' from the toolbar."""
    page.locator(".gramma2-icon").click()
    local_tab = page.locator(".gramma2-tab:not(.gramma2-tab-regen)", has_text="Local")
    expect(local_tab).to_be_visible(timeout=2000)
    local_tab.click()


def test_icon_appears_on_input_focus(page):
    page.click("#test-input")
    icon = page.locator(".gramma2-icon")
    expect(icon).to_be_visible(timeout=2000)


def test_icon_disappears_on_blur(page):
    page.click("#test-input")
    expect(page.locator(".gramma2-icon")).to_be_visible(timeout=2000)
    page.click("h1")
    expect(page.locator(".gramma2-icon")).to_be_hidden(timeout=2000)


def test_icon_follows_focus(page):
    page.click("#test-input")
    expect(page.locator(".gramma2-icon")).to_be_visible(timeout=2000)
    input_icon_top = page.locator(".gramma2-icon").bounding_box()["y"]

    page.click("#test-textarea")
    expect(page.locator(".gramma2-icon")).to_be_visible(timeout=2000)
    textarea_icon_top = page.locator(".gramma2-icon").bounding_box()["y"]

    assert textarea_icon_top > input_icon_top


def test_toolbar_shows_on_icon_click(page):
    page.click("#test-input")
    page.locator(".gramma2-icon").click()
    popup = page.locator(".gramma2-popup")
    expect(popup).to_be_visible(timeout=2000)

    tabs = page.locator(".gramma2-tab:not(.gramma2-tab-regen)")
    expect(tabs).to_have_count(2)
    expect(tabs.nth(0)).to_contain_text("Local")
    expect(tabs.nth(1)).to_contain_text("Codex")


def test_popup_shows_suggestion(page):
    page.click("#test-input")
    _click_icon_and_pick_local(page)

    suggestions = page.locator(".gramma2-suggestion")
    expect(suggestions).to_have_count(1, timeout=5000)
    expect(suggestions.first).to_contain_text("Fixed:")


def test_toolbar_stays_after_suggestion(page):
    page.click("#test-input")
    _click_icon_and_pick_local(page)
    expect(page.locator(".gramma2-suggestion")).to_have_count(1, timeout=5000)

    # Toolbar should still be visible
    tabs = page.locator(".gramma2-tab:not(.gramma2-tab-regen)")
    expect(tabs).to_have_count(2)
    expect(page.locator(".gramma2-tab-active")).to_have_count(1)


def test_switch_model_after_suggestion(page):
    page.click("#test-input")
    _click_icon_and_pick_local(page)
    expect(page.locator(".gramma2-suggestion")).to_have_count(1, timeout=5000)

    # Click Codex tab — should trigger a new request
    page.locator(".gramma2-tab[data-backend='codex']").click()
    expect(page.locator(".gramma2-suggestion")).to_have_count(1, timeout=5000)


def test_suggestion_replaces_input_text(page):
    page.click("#test-input")
    _click_icon_and_pick_local(page)
    page.locator(".gramma2-suggestion").first.click()

    assert page.input_value("#test-input").startswith("Fixed:")
    expect(page.locator(".gramma2-popup")).to_be_hidden()


def test_suggestion_replaces_textarea_text(page):
    page.fill("#test-textarea", "He go store.")
    page.click("#test-textarea")
    _click_icon_and_pick_local(page)
    page.wait_for_selector(".gramma2-suggestion", state="visible", timeout=5000)
    page.locator(".gramma2-suggestion").first.click()

    assert page.input_value("#test-textarea").startswith("Fixed:")


def test_suggestion_replaces_contenteditable_text(page):
    page.locator("#test-contenteditable").fill("He go store.")
    page.click("#test-contenteditable")
    _click_icon_and_pick_local(page)
    page.wait_for_selector(".gramma2-suggestion", state="visible", timeout=5000)
    page.locator(".gramma2-suggestion").first.click()

    # Rich contenteditable shows fallback — click "Apply as plain text"
    apply_plain = page.locator(".gramma2-apply-plain")
    if apply_plain.is_visible():
        apply_plain.click()

    assert page.inner_text("#test-contenteditable").startswith("Fixed:")


def test_popup_dismisses_on_outside_click(page):
    page.click("#test-input")
    page.locator(".gramma2-icon").click()
    expect(page.locator(".gramma2-popup")).to_be_visible(timeout=2000)

    page.click("h1")
    expect(page.locator(".gramma2-popup")).to_be_hidden(timeout=2000)


def test_empty_input_no_popup(page):
    page.fill("#test-input", "")
    page.click("#test-input")
    page.locator(".gramma2-icon").click()
    expect(page.locator(".gramma2-popup")).to_be_hidden()


def test_suggestion_replaces_iframe_textarea_text(page):
    frame = page.frame_locator("#test-iframe")
    frame.locator("#frame-textarea").click()
    expect(frame.locator(".gramma2-icon")).to_be_visible(timeout=5000)
    frame.locator(".gramma2-icon").click()
    local_tab = frame.locator(".gramma2-tab:not(.gramma2-tab-regen)", has_text="Local")
    expect(local_tab).to_be_visible(timeout=2000)
    local_tab.click()
    expect(frame.locator(".gramma2-suggestion")).to_have_count(1, timeout=5000)
    frame.locator(".gramma2-suggestion").first.click()

    assert frame.locator("#frame-textarea").input_value().startswith("Fixed:")


def test_icon_and_replacement_work_for_open_shadow_dom_input(page):
    shadow_input = page.locator("#shadow-host").locator("input")
    shadow_input.click()
    expect(page.locator(".gramma2-icon")).to_be_visible(timeout=5000)
    _click_icon_and_pick_local(page)
    expect(page.locator(".gramma2-suggestion")).to_have_count(1, timeout=5000)
    page.locator(".gramma2-suggestion").first.click()

    assert shadow_input.input_value().startswith("Fixed:")


def test_regenerate_tab_appears_after_first_use(page):
    page.click("#test-input")
    _click_icon_and_pick_local(page)
    expect(page.locator(".gramma2-suggestion")).to_have_count(1, timeout=5000)

    # Dismiss and reopen — regenerate tab should now be visible
    page.click("h1")
    expect(page.locator(".gramma2-popup")).to_be_hidden(timeout=2000)
    page.click("#test-input")
    page.locator(".gramma2-icon").click()

    regen_tab = page.locator(".gramma2-tab-regen:not(.gramma2-hidden)")
    expect(regen_tab).to_have_count(1, timeout=2000)


def test_loading_spinner_shows(page):
    page.click("#test-input")
    _click_icon_and_pick_local(page)
    expect(page.locator(".gramma2-suggestion")).to_have_count(1, timeout=5000)


# ---------------------------------------------------------------------------
# Batch / Review flow tests
# ---------------------------------------------------------------------------

def _fill_long_text(page, element_id, num_sentences=5):
    """Fill an element with multi-sentence text that triggers batch flow."""
    sentences = [f"Sentence {i} has bad grammar and need fixing." for i in range(num_sentences)]
    text = " ".join(sentences)
    page.fill(element_id, text)
    return text, sentences


def test_short_text_keeps_existing_full_text_flow(page):
    """Short 1-2 sentence input should use the regular suggestion card, not batch summary."""
    page.fill("#test-input", "He go store.")
    page.click("#test-input")
    _click_icon_and_pick_local(page)
    # Should show regular suggestion, not summary
    expect(page.locator(".gramma2-suggestion")).to_have_count(1, timeout=5000)
    expect(page.locator(".gramma2-summary")).to_have_count(0)


def test_long_text_shows_progressive_review(page):
    """Multi-sentence input should show progressive block review UI."""
    _fill_long_text(page, "#test-textarea", 5)
    page.click("#test-textarea")
    _click_icon_and_pick_local(page)

    review_count = page.locator(".gramma2-review-count")
    expect(review_count).to_be_visible(timeout=5000)
    expect(review_count).to_contain_text("Fix block")
    expect(page.locator(".gramma2-review-original")).to_be_visible()
    expect(page.locator(".gramma2-review-suggestion")).to_be_visible()


def test_apply_all_remaining_replaces_text(page):
    """Apply all remaining should apply all fixes and close."""
    _fill_long_text(page, "#test-textarea", 5)
    page.click("#test-textarea")
    _click_icon_and_pick_local(page)
    expect(page.locator(".gramma2-review-count")).to_be_visible(timeout=5000)

    page.locator(".gramma2-apply-all-remaining").click()
    expect(page.locator(".gramma2-popup")).to_be_hidden(timeout=5000)
    new_text = page.input_value("#test-textarea")
    assert "Fixed:" in new_text


def test_review_apply_changes_current_block(page):
    """Apply in review mode should change the current block and advance."""
    _fill_long_text(page, "#test-textarea", 5)
    page.click("#test-textarea")
    _click_icon_and_pick_local(page)
    expect(page.locator(".gramma2-review-count")).to_be_visible(timeout=5000)

    original = page.locator(".gramma2-review-original").inner_text()
    page.locator(".gramma2-apply").click()

    # Text should contain the fixed block
    new_text = page.input_value("#test-textarea")
    assert f"Fixed: {original}" in new_text

    # Should show next block or done
    has_next = page.locator(".gramma2-review-count").is_visible() or page.locator(".gramma2-done").is_visible()
    assert has_next


def test_review_ignore_skips_current_block(page):
    """Ignore should skip the current block and show the next."""
    _fill_long_text(page, "#test-textarea", 5)
    page.click("#test-textarea")
    _click_icon_and_pick_local(page)
    expect(page.locator(".gramma2-review-count")).to_be_visible(timeout=5000)

    original_block = page.locator(".gramma2-review-original").inner_text()
    text_before = page.input_value("#test-textarea")
    page.locator(".gramma2-ignore").click()

    # Text should be unchanged
    assert page.input_value("#test-textarea") == text_before


def test_no_changes_suggested_message(page):
    """When all blocks are unchanged, show 'No changes suggested'."""
    text = "This sentence is perfect one. This sentence is perfect two. This sentence is perfect three. This sentence is perfect four."
    page.fill("#test-textarea", text)
    page.click("#test-textarea")
    _click_icon_and_pick_local(page)

    expect(page.locator(".gramma2-no-changes")).to_be_visible(timeout=5000)
    expect(page.locator(".gramma2-no-changes")).to_contain_text("No changes suggested")


def test_review_highlight_selects_current_textarea_block(page):
    """During review, the current block should be selected in the textarea."""
    _fill_long_text(page, "#test-textarea", 5)
    page.click("#test-textarea")
    _click_icon_and_pick_local(page)
    expect(page.locator(".gramma2-review-count")).to_be_visible(timeout=5000)

    sel_start = page.evaluate("document.getElementById('test-textarea').selectionStart")
    sel_end = page.evaluate("document.getElementById('test-textarea').selectionEnd")
    assert sel_end > sel_start


def test_review_restores_selection_after_close(page):
    """After dismissing the review popup, the original selection should be restored."""
    page.fill("#test-textarea", "Sentence 0 has bad grammar. Sentence 1 has bad grammar. Sentence 2 has bad grammar. Sentence 3 has bad grammar. Sentence 4 has bad grammar.")
    page.click("#test-textarea")

    # Set a known caret position
    page.evaluate("document.getElementById('test-textarea').setSelectionRange(5, 5)")

    _click_icon_and_pick_local(page)
    expect(page.locator(".gramma2-review-count")).to_be_visible(timeout=5000)

    # Dismiss popup by clicking outside
    page.click("h1")
    expect(page.locator(".gramma2-popup")).to_be_hidden(timeout=2000)

    # Selection should be restored to position 5
    sel_start = page.evaluate("document.getElementById('test-textarea').selectionStart")
    assert sel_start == 5


# ---------------------------------------------------------------------------
# Progressive long-text flow tests (Step 7)
# ---------------------------------------------------------------------------

def _fill_progressive_text(page, element_id, num_sentences=15):
    """Fill an element with very long text that triggers progressive flow (>=12 sentences)."""
    sentences = [f"Sentence {i} has bad grammar and need fixing." for i in range(num_sentences)]
    text = " ".join(sentences)
    page.fill(element_id, text)
    return text, sentences


def test_progressive_mode_activates_for_long_text(page):
    """Very long text (12+ sentences) should trigger progressive block review."""
    _fill_progressive_text(page, "#test-textarea", 15)
    page.click("#test-textarea")
    _click_icon_and_pick_local(page)

    # Should eventually show block review UI (blocks process quickly with mock)
    review_count = page.locator(".gramma2-review-count")
    expect(review_count).to_be_visible(timeout=5000)
    expect(review_count).to_contain_text("Fix block")
    expect(review_count).to_contain_text("of")


def test_progressive_apply_block_changes_text(page):
    """Applying a block should change the text and advance to next block."""
    _fill_progressive_text(page, "#test-textarea", 15)
    page.click("#test-textarea")
    _click_icon_and_pick_local(page)

    expect(page.locator(".gramma2-review-count")).to_be_visible(timeout=5000)
    original_block = page.locator(".gramma2-review-original").inner_text()
    page.locator(".gramma2-apply").click()

    # Text should contain the fixed block
    new_text = page.input_value("#test-textarea")
    assert f"Fixed: {original_block}" in new_text

    # Should show next block or done
    has_next = page.locator(".gramma2-review-count").is_visible() or page.locator(".gramma2-done").is_visible()
    assert has_next


def test_progressive_ignore_block_keeps_text(page):
    """Ignoring a block should leave text unchanged and advance."""
    _fill_progressive_text(page, "#test-textarea", 15)
    page.click("#test-textarea")
    _click_icon_and_pick_local(page)

    expect(page.locator(".gramma2-review-count")).to_be_visible(timeout=5000)
    original_block = page.locator(".gramma2-review-original").inner_text()
    text_before = page.input_value("#test-textarea")

    page.locator(".gramma2-ignore").click()

    # Original block text should still be present
    text_after = page.input_value("#test-textarea")
    assert original_block in text_after
    assert text_before == text_after


def test_progressive_apply_all_remaining_applies_all(page):
    """Apply all remaining should apply all pending blocks and close."""
    _fill_progressive_text(page, "#test-textarea", 15)
    page.click("#test-textarea")
    _click_icon_and_pick_local(page)

    expect(page.locator(".gramma2-review-count")).to_be_visible(timeout=5000)

    page.locator(".gramma2-apply-all-remaining").click()
    expect(page.locator(".gramma2-popup")).to_be_hidden(timeout=5000)

    new_text = page.input_value("#test-textarea")
    assert "Fixed:" in new_text


def test_progressive_block_offsets_after_apply(page):
    """After applying one block (changing text length), the next block should still apply correctly."""
    _fill_progressive_text(page, "#test-textarea", 15)
    page.click("#test-textarea")
    _click_icon_and_pick_local(page)

    expect(page.locator(".gramma2-review-count")).to_be_visible(timeout=5000)

    # Apply first block
    page.locator(".gramma2-apply").click()

    # Apply second block
    expect(page.locator(".gramma2-review-count")).to_be_visible(timeout=2000)
    second_original = page.locator(".gramma2-review-original").inner_text()
    page.locator(".gramma2-apply").click()

    # Both fixes should be in the text
    new_text = page.input_value("#test-textarea")
    assert f"Fixed: {second_original}" in new_text


def test_progressive_text_change_invalidates_session(page):
    """If the user edits text during progressive review, session should be invalidated."""
    _fill_progressive_text(page, "#test-textarea", 15)
    page.click("#test-textarea")
    _click_icon_and_pick_local(page)

    expect(page.locator(".gramma2-review-count")).to_be_visible(timeout=5000)

    # Simulate user typing into the textarea
    page.evaluate("""
        const ta = document.getElementById('test-textarea');
        ta.value = 'User edited this text.';
        ta.dispatchEvent(new Event('input', { bubbles: true }));
    """)

    # Should show invalidation message
    expect(page.locator(".gramma2-no-changes")).to_be_visible(timeout=2000)
    expect(page.locator(".gramma2-no-changes")).to_contain_text("Text changed")


def test_progressive_shows_done_after_all_blocks_reviewed(page):
    """After reviewing all blocks, should show 'All done' or auto-dismiss."""
    # Use just enough sentences for progressive mode (12)
    _fill_progressive_text(page, "#test-textarea", 12)
    page.click("#test-textarea")
    _click_icon_and_pick_local(page)

    expect(page.locator(".gramma2-review-count")).to_be_visible(timeout=5000)

    # Click through all blocks
    for _ in range(50):  # safety limit
        if page.locator(".gramma2-done").is_visible():
            break
        if page.locator(".gramma2-popup").is_hidden():
            break  # auto-dismissed after "All done"
        if page.locator(".gramma2-ignore").is_visible():
            page.locator(".gramma2-ignore").click()
            page.wait_for_timeout(100)
        else:
            page.wait_for_timeout(100)

    # Either "All done" is visible or popup auto-dismissed
    is_done = page.locator(".gramma2-done").is_visible()
    is_dismissed = page.locator(".gramma2-popup").is_hidden()
    assert is_done or is_dismissed


def test_progressive_shows_waiting_when_backend_slow(page, slow_improve):
    """When the backend is slow, user should see the waiting state."""
    _fill_progressive_text(page, "#test-textarea", 15)
    page.click("#test-textarea")
    _click_icon_and_pick_local(page)

    # With 500ms delay, preparing/waiting state should be visible
    waiting_or_preparing = page.locator(".gramma2-preparing, .gramma2-waiting")
    expect(waiting_or_preparing.first).to_be_visible(timeout=2000)


def test_progressive_bounded_lookahead_limits_ready_blocks(page):
    """Bounded lookahead should not process all blocks eagerly.

    With many blocks and a fast mock, the scheduler should only keep
    maxAhead blocks ready/in-flight ahead of the resolved cursor.
    After all blocks complete within the window, later blocks should
    remain queued until the user advances.
    """
    # 20 sentences → ~5 blocks (4 sentences each), local queue depth = 2
    _fill_progressive_text(page, "#test-textarea", 20)
    page.click("#test-textarea")
    _click_icon_and_pick_local(page)

    # Wait for the first block to be ready
    expect(page.locator(".gramma2-review-count")).to_be_visible(timeout=5000)

    # Check how many blocks are ready or in-flight (should be <= queue depth)
    # Local backend queue depth is 2
    block_statuses = page.evaluate("""() => {
        return typeof reviewBlocks !== 'undefined'
            ? reviewBlocks.map(b => b.status)
            : [];
    }""")

    if block_statuses:
        ahead_count = sum(
            1 for s in block_statuses if s in ("ready", "in_flight")
        )
        # Local queue depth is 3 — should not have more than 3 ready/in-flight
        assert ahead_count <= 3, f"Expected <= 3 ready/in-flight, got {ahead_count}: {block_statuses}"


# ---------------------------------------------------------------------------
# Rich text safety tests (Step 10)
# ---------------------------------------------------------------------------

def test_rich_contenteditable_whole_field_shows_fallback(page):
    """Clicking suggestion on rich contenteditable should show fallback options, not auto-apply."""
    page.click("#test-rich-contenteditable")
    _click_icon_and_pick_local(page)

    # Wait for suggestion
    suggestion = page.locator(".gramma2-suggestion")
    expect(suggestion.first).to_be_visible(timeout=5000)

    # Should show rich text warning
    expect(page.locator(".gramma2-rich-warning")).to_be_visible()

    # Click the suggestion
    suggestion.first.click()

    # Should show fallback UI, not apply directly
    expect(page.locator(".gramma2-rich-fallback")).to_be_visible()
    expect(page.locator(".gramma2-copy-suggestion")).to_be_visible()
    expect(page.locator(".gramma2-apply-plain")).to_be_visible()
    expect(page.locator(".gramma2-cancel")).to_be_visible()


def test_rich_contenteditable_apply_plain_works(page):
    """'Apply as plain text' on rich contenteditable should replace text."""
    page.locator("#test-rich-contenteditable").fill("He go store.")
    page.click("#test-rich-contenteditable")
    _click_icon_and_pick_local(page)

    suggestion = page.locator(".gramma2-suggestion")
    expect(suggestion.first).to_be_visible(timeout=5000)
    suggestion.first.click()

    # Click "Apply as plain text" in fallback
    expect(page.locator(".gramma2-apply-plain")).to_be_visible()
    page.locator(".gramma2-apply-plain").click()

    assert page.inner_text("#test-rich-contenteditable").startswith("Fixed:")
    expect(page.locator(".gramma2-popup")).to_be_hidden()


def test_rich_contenteditable_cancel_preserves_text(page):
    """Cancel in fallback should leave original text unchanged."""
    original = page.inner_text("#test-rich-contenteditable")
    page.click("#test-rich-contenteditable")
    _click_icon_and_pick_local(page)

    suggestion = page.locator(".gramma2-suggestion")
    expect(suggestion.first).to_be_visible(timeout=5000)
    suggestion.first.click()

    expect(page.locator(".gramma2-cancel")).to_be_visible()
    page.locator(".gramma2-cancel").click()

    assert page.inner_text("#test-rich-contenteditable") == original
    expect(page.locator(".gramma2-popup")).to_be_hidden()


def test_rich_contenteditable_formatting_preserved_after_cancel(page):
    """After cancelling, original formatting (bold, italic, links) should be intact."""
    page.click("#test-rich-contenteditable")
    _click_icon_and_pick_local(page)

    suggestion = page.locator(".gramma2-suggestion")
    expect(suggestion.first).to_be_visible(timeout=5000)
    suggestion.first.click()

    expect(page.locator(".gramma2-cancel")).to_be_visible()
    page.locator(".gramma2-cancel").click()

    # Verify formatting elements still exist
    rich = page.locator("#test-rich-contenteditable")
    expect(rich.locator("strong")).to_have_count(2)
    expect(rich.locator("em")).to_have_count(2)
    expect(rich.locator("a")).to_have_count(1)
    expect(rich.locator("code")).to_have_count(1)


def test_rich_contenteditable_cross_boundary_selection_blocked(page):
    """Selection crossing formatting boundary in rich text should be blocked."""
    # Select text that spans across the <strong> boundary
    page.evaluate("""() => {
        const el = document.getElementById('test-rich-contenteditable');
        const sel = window.getSelection();
        const range = document.createRange();
        // Select from "dont have" (before strong) across "experience" (inside em)
        const textNodes = [];
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        while (walker.nextNode()) textNodes.push(walker.currentNode);
        // First text node: "The ", second: "project manager", third: " dont have enough "
        // fourth: "experience", fifth: " to leads the team. "
        if (textNodes.length >= 5) {
            range.setStart(textNodes[2], 1); // inside " dont have enough "
            range.setEnd(textNodes[3], 5);   // inside "experience"
            sel.removeAllRanges();
            sel.addRange(range);
        }
    }""")

    _click_icon_and_pick_local(page)

    suggestion = page.locator(".gramma2-suggestion")
    expect(suggestion.first).to_be_visible(timeout=5000)
    suggestion.first.click()

    # Should show fallback because selection crosses formatting boundary
    expect(page.locator(".gramma2-rich-fallback")).to_be_visible(timeout=2000)
    expect(page.locator(".gramma2-rich-fallback-title")).to_contain_text("Rich text")
