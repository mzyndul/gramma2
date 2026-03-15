PROMPT_TEMPLATE = """\
Fix grammar and spelling in the text below. Keep the original meaning and tone.
If the text is already correct, return it unchanged.
Do NOT explain, ask questions, or add commentary. Return ONLY the corrected text.

Output ONLY valid JSON: {{"suggestion": "corrected text"}}

Text:
{text}"""
