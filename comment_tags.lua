-- comment_tags.lua
-- Supports:
--   Inline: <comment>...</comment>, <comment-left>...</comment-left>, <comment-right>...</comment-right>
--   Block:  same tags wrapping block content (lists, multiple paras, etc.)
--
-- Inline output:
--   <span class="comment-pin"><span class="comment-right|left">...</span></span>
--
-- Block output:
--   <span class="comment-pin comment-pin-block" data-comment-id="cN"></span>
--   <div class="comment-overlay comment-right|left" data-comment-id="cN"> ...block content... </div>
--
-- Requires JS to position .comment-overlay.

local function raw_inline_html(el)
  if el and el.t == "RawInline" and el.format == "html" then
    return el.text:lower()
  end
  return nil
end

local function raw_block_html(el)
  if el and el.t == "RawBlock" and el.format == "html" then
    return el.text:lower()
  end
  return nil
end

local OPENERS = {
  ["<comment>"]       = { side = "comment-right", close = "</comment>" },
  ["<comment-right>"] = { side = "comment-right", close = "</comment-right>" },
  ["<comment-left>"]  = { side = "comment-left",  close = "</comment-left>"  },
}

local comment_id = 0
local function next_id()
  comment_id = comment_id + 1
  return "c" .. tostring(comment_id)
end

local function make_inline_comment(side, content_inlines)
  local inner = pandoc.Span(content_inlines, pandoc.Attr("", { side }, {}))
  return pandoc.Span(pandoc.List({ inner }), pandoc.Attr("", { "comment-pin" }, {}))
end

local function make_block_anchor(id)
  -- RawBlock so we don't introduce a <p> wrapper that changes spacing
  return pandoc.RawBlock("html",
    '<span class="comment-pin comment-pin-block" data-comment-id="' .. id .. '"></span>')
end

local function make_block_overlay(side, id, content_blocks)
  -- Div can contain BulletList/Para/etc. JS will position this overlay.
  return pandoc.Div(
    content_blocks,
    pandoc.Attr("", { "comment-overlay", side }, { ["data-comment-id"] = id })
  )
end

local function para_like_t(block)
  return block and (block.t == "Para" or block.t == "Plain")
end

local function clone_para_like(block, inlines)
  if block.t == "Para" then
    return pandoc.Para(inlines)
  else
    return pandoc.Plain(inlines)
  end
end

-- Detect opener at block level:
--   1) RawBlock("<comment>")
--   2) first inline of Para/Plain is RawInline("<comment>")
-- Returns: spec, stripped_block_or_nil
local function detect_block_opener(block)
  local t = raw_block_html(block)
  local spec = t and OPENERS[t] or nil
  if spec then
    return spec, nil
  end

  if para_like_t(block) and #block.content > 0 then
    local t0 = raw_inline_html(block.content[1])
    local spec2 = t0 and OPENERS[t0] or nil
    if spec2 then
      local rest = pandoc.List()
      for k = 2, #block.content do
        rest:insert(block.content[k])
      end
      if #rest == 0 then
        return spec2, nil
      else
        return spec2, clone_para_like(block, rest)
      end
    end
  end

  return nil, nil
end

-- Detect closer at block level:
--   1) RawBlock("</comment>")
--   2) last inline of Para/Plain is RawInline("</comment>")
-- Returns: found_bool, stripped_block_or_nil
local function strip_block_closer(block, close_tag)
  local t = raw_block_html(block)
  if t == close_tag then
    return true, nil
  end

  if para_like_t(block) and #block.content > 0 then
    local tn = raw_inline_html(block.content[#block.content])
    if tn == close_tag then
      local rest = pandoc.List()
      for k = 1, #block.content - 1 do
        rest:insert(block.content[k])
      end
      if #rest == 0 then
        return true, nil
      else
        return true, clone_para_like(block, rest)
      end
    end
  end

  return false, nil
end

-- Inline comments (mid-paragraph)
function Inlines(inlines)
  local out = pandoc.List()
  local i, n = 1, #inlines

  while i <= n do
    local t = raw_inline_html(inlines[i])
    local spec = t and OPENERS[t] or nil

    if not spec then
      out:insert(inlines[i])
      i = i + 1
    else
      local buf = pandoc.List()
      local j = i + 1
      local found = false

      while j <= n do
        local tj = raw_inline_html(inlines[j])
        if tj == spec.close then
          found = true
          break
        end
        buf:insert(inlines[j])
        j = j + 1
      end

      if found then
        out:insert(make_inline_comment(spec.side, buf))
        i = j + 1
      else
        -- unmatched: leave literal
        out:insert(inlines[i])
        i = i + 1
      end
    end
  end

  return out
end

-- Block comments (lists / multi-paragraph inside <comment> ... </comment>)
function Blocks(blocks)
  local out = pandoc.List()
  local i, n = 1, #blocks

  while i <= n do
    local spec, stripped_first = detect_block_opener(blocks[i])

    if not spec then
      out:insert(blocks[i])
      i = i + 1
    else
      local buf = pandoc.List()
      if stripped_first then
        buf:insert(stripped_first)
      end

      local j = i + 1
      local found = false

      while j <= n do
        local is_close, stripped = strip_block_closer(blocks[j], spec.close)
        if is_close then
          if stripped then
            buf:insert(stripped)
          end
          found = true
          break
        else
          buf:insert(blocks[j])
        end
        j = j + 1
      end

      if found then
        local id = next_id()
        out:insert(make_block_anchor(id))
        out:insert(make_block_overlay(spec.side, id, buf))
        i = j + 1
      else
        -- unmatched opener: preserve original block
        out:insert(blocks[i])
        i = i + 1
      end
    end
  end

  return out
end