from pydifftools.notebook.tex_to_qmd import format_tags

def test_err_block_ensures_blank_line_after_close():
    text = "<err>\ninner\n</err>Next section\n"
    formatted = format_tags(text)
    assert "</err>\n\nNext section" in formatted
