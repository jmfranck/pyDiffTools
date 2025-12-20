from pydifftools.notebook.tex_to_qmd import format_tags

def test_err_block_ensures_blank_line_after_close():
    text = "<err>\ninner\n</err>Next section\n"
    formatted = format_tags(text)
    expected = "<err>\n  inner\n</err>\n\nNext section\n"
    assert formatted == expected

def test_err_block_allows_br_after_close():
    text = "<err>\ninner\n</err>\n<br/>\n"
    formatted = format_tags(text)
    expected = "<err>\n  inner\n</err>\n\n<br/>\n"
    assert formatted == expected
