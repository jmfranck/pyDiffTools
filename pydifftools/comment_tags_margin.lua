-- comment_tags_margin.lua
-- PYDIFFTOOLS_SPECIAL_MARGIN_COMMENTS_FILTER
-- Supports:
--   Inline: <comment>...</comment>, <comment-left>...</comment-left>,
--           <comment-right>...</comment-right>
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
  ["<comment>"] = { side = "comment-left", close = "</comment>" },
  ["<comment-right>"] = { side = "comment-left", close = "</comment-right>" },
  ["<comment-left>"] = { side = "comment-left", close = "</comment-left>" },
}

local comment_id = 0
local function next_id()
  comment_id = comment_id + 1
  return "c" .. tostring(comment_id)
end

local function make_inline_comment(side, content_inlines)
  -- Emit inline comments as overlay-positioned margin bubbles so they stay in
  -- the left margin without forcing a paragraph break at the insertion point.
  local id = next_id()
  local out = pandoc.List()
  out:insert(
    pandoc.RawInline(
      "html",
      '<span class="comment-inline-break-marker comment-inline-break-before">...</span>'
    )
  )
  out:insert(
    pandoc.RawInline(
      "html",
      '<span class="comment-pin comment-pin-block" data-comment-id="' .. id .. '"></span>'
    )
  )
  out:insert(
    pandoc.Span(
      content_inlines,
      pandoc.Attr(
        "",
        { "comment-overlay", side, "comment-inline-margin", "comment-margin-left" },
        { ["data-comment-id"] = id, ["style"] = "font-size: 6pt;" }
      )
    )
  )
  out:insert(
    pandoc.RawInline(
      "html",
      '<span class="comment-inline-break-marker comment-inline-break-after">...</span>'
    )
  )
  return out
end

local function make_block_anchor(id)
  -- RawBlock so we don't introduce a <p> wrapper that changes spacing.
  return pandoc.RawBlock("html",
    '<span class="comment-pin comment-pin-block" data-comment-id="' .. id .. '"></span>')
end

local function make_block_overlay(side, id, content_blocks)
  -- Div can contain BulletList/Para/etc. JS will position this overlay.
  return pandoc.Div(
    content_blocks,
    pandoc.Attr(
      "",
      { "comment-overlay", side, "comment-margin-left" },
      { ["data-comment-id"] = id, ["style"] = "font-size: 6pt;" }
    )
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

local function split_inline_block_at_tag(block, tag)
  if not para_like_t(block) then
    return false, nil, nil
  end

  local tag_index = nil
  for j = 1, #block.content do
    if raw_inline_html(block.content[j]) == tag then
      tag_index = j
      break
    end
  end
  if not tag_index then
    return false, nil, nil
  end

  local before = pandoc.List()
  local after = pandoc.List()
  for j = 1, tag_index - 1 do
    before:insert(block.content[j])
  end
  for j = tag_index + 1, #block.content do
    after:insert(block.content[j])
  end

  -- Avoid creating hard visual breaks around opener/closer tags when those
  -- tags sit at line boundaries in markdown source.
  while #before > 0 and (
    before[#before].t == "SoftBreak"
    or before[#before].t == "LineBreak"
    or before[#before].t == "Space"
  ) do
    before:remove(#before)
  end
  while #after > 0 and (
    after[1].t == "SoftBreak"
    or after[1].t == "LineBreak"
    or after[1].t == "Space"
  ) do
    after:remove(1)
  end

  local before_block = nil
  local after_block = nil
  if #before > 0 then
    before_block = clone_para_like(block, before)
  end
  if #after > 0 then
    after_block = clone_para_like(block, after)
  end

  return true, before_block, after_block
end


local function split_block_at_closer(block, close_tag)
  -- Handle direct Para/Plain closer first.
  if para_like_t(block) then
    local found, before, after = split_inline_block_at_tag(block, close_tag)
    if found then
      local after_blocks = pandoc.List()
      if after then
        after_blocks:insert(after)
      end
      return true, before, after_blocks
    end
    return false, nil, pandoc.List()
  end

  -- Handle list blocks where the closer can appear inside a list item.
  if block.t == "BulletList" then
    local before_items = pandoc.List()
    local after_blocks = pandoc.List()

    for item_index = 1, #block.content do
      local this_item = block.content[item_index]
      local before_item_blocks = pandoc.List()

      for block_index = 1, #this_item do
        local found, before, nested_after =
          split_block_at_closer(this_item[block_index], close_tag)
        if found then
          if before then
            before_item_blocks:insert(before)
          end
          if #before_item_blocks > 0 then
            before_items:insert(before_item_blocks)
          end

          -- Once the comment closes, flatten the remaining list content back
          -- into normal blocks so we do not leak list text into body lists.
          for nested_index = 1, #nested_after do
            after_blocks:insert(nested_after[nested_index])
          end
          for k = block_index + 1, #this_item do
            after_blocks:insert(this_item[k])
          end
          for item_tail = item_index + 1, #block.content do
            for tail_block_index = 1, #block.content[item_tail] do
              after_blocks:insert(block.content[item_tail][tail_block_index])
            end
          end

          local before_block = nil
          if #before_items > 0 then
            before_block = pandoc.BulletList(before_items)
          end
          return true, before_block, after_blocks
        else
          before_item_blocks:insert(this_item[block_index])
        end
      end

      if #before_item_blocks > 0 then
        before_items:insert(before_item_blocks)
      end
    end

    return false, nil, pandoc.List()
  end

  return false, nil, pandoc.List()
end

-- Detect opener at block level:
--   1) RawBlock("<comment>")
--   2) anywhere inside Para/Plain as RawInline("<comment>")
-- Returns: spec, before_block_or_nil, after_block_or_nil
local function detect_block_opener(block)
  local t = raw_block_html(block)
  local spec = t and OPENERS[t] or nil
  if spec then
    return spec, nil, nil
  end

  if para_like_t(block) then
    for k, opener_spec in pairs(OPENERS) do
      local found, before, after = split_inline_block_at_tag(block, k)
      if found then
        return opener_spec, before, after
      end
    end
  end

  return nil, nil, nil
end

-- Detect closer at block level:
--   1) RawBlock("</comment>")
--   2) anywhere inside Para/Plain as RawInline("</comment>")
-- Returns: found_bool, before_block_or_nil, after_block_or_nil
local function strip_block_closer(block, close_tag)
  local t = raw_block_html(block)
  if t == close_tag then
    return true, nil, pandoc.List()
  end

  local found, before, after_blocks = split_block_at_closer(block, close_tag)
  if found then
    return true, before, after_blocks
  end

  return false, nil, pandoc.List()
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
        local margin_comment = make_inline_comment(spec.side, buf)
        for k = 1, #margin_comment do
          out:insert(margin_comment[k])
        end
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
    local spec, before_open, after_open = detect_block_opener(blocks[i])

    if not spec then
      out:insert(blocks[i])
      i = i + 1
    else
      local buf = pandoc.List()
      local inserted_before_open = false
      if before_open then
        -- Keep text before the opener in the main document flow.
        out:insert(before_open)
        inserted_before_open = true
      end
      if after_open then
        -- Everything after the opener belongs inside the bubble body.
        buf:insert(after_open)
      end

      local j = i + 1
      local found = false
      local after_close_blocks = pandoc.List()

      while j <= n do
        local is_close, before_close, after_close_candidate =
          strip_block_closer(blocks[j], spec.close)
        if is_close then
          if before_close then
            buf:insert(before_close)
          end
          found = true
          after_close_blocks = after_close_candidate
          break
        else
          buf:insert(blocks[j])
        end
        j = j + 1
      end

      if found then
        local id = next_id()
        local merged_with_inline_anchor = false

        -- If the comment opens mid-paragraph and closes before trailing prose,
        -- merge the surrounding prose back into one paragraph and place the
        -- anchor inline at the split point so there is no forced line break.
        if inserted_before_open and #after_close_blocks > 0 then
          if para_like_t(out[#out]) and para_like_t(after_close_blocks[1]) then
            local merged_inlines = pandoc.List()
            for k = 1, #out[#out].content do
              merged_inlines:insert(out[#out].content[k])
            end
            merged_inlines:insert(
              pandoc.RawInline(
                "html",
                '<span class="comment-pin comment-pin-block" data-comment-id="'
                  .. id .. '"></span>'
              )
            )
            merged_inlines:insert(pandoc.Space())
            for k = 1, #after_close_blocks[1].content do
              merged_inlines:insert(after_close_blocks[1].content[k])
            end
            out[#out] = clone_para_like(out[#out], merged_inlines)
            after_close_blocks:remove(1)
            merged_with_inline_anchor = true
          end
        end

        if not merged_with_inline_anchor then
          out:insert(make_block_anchor(id))
        end
        out:insert(make_block_overlay(spec.side, id, buf))

        -- Keep trailing content after the closer in main flow.
        for after_index = 1, #after_close_blocks do
          out:insert(after_close_blocks[after_index])
        end
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
