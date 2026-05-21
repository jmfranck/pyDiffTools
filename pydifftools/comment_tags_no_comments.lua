-- comment_tags_no_comments.lua
-- PYDIFFTOOLS_SPECIAL_NO_COMMENTS_FILTER
-- Supports:
--   Inline: <comment>...</comment>, <comment-left>...</comment-left>,
--           <comment-right>...</comment-right>
--   Block:  same tags wrapping block content (lists, multiple paras, etc.)
--
-- Removes supported comments from the rendered document while preserving
-- surrounding prose and normal block structure.

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
  ["<comment>"] = { close = "</comment>" },
  ["<comment-right>"] = { close = "</comment-right>" },
  ["<comment-left>"] = { close = "</comment-left>" },
}

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

local function has_comment_class(el)
  if not el or not el.classes then
    return false
  end
  for _, class_name in ipairs(el.classes) do
    if class_name == "comment-right" or class_name == "comment-left" then
      return true
    end
  end
  return false
end

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
      local j = i + 1
      local found = false

      while j <= n do
        local tj = raw_inline_html(inlines[j])
        if tj == spec.close then
          found = true
          break
        end
        j = j + 1
      end

      if found then
        i = j + 1
      else
        out:insert(inlines[i])
        i = i + 1
      end
    end
  end

  return out
end

function Blocks(blocks)
  local out = pandoc.List()
  local i, n = 1, #blocks

  while i <= n do
    local spec, before_open, after_open = detect_block_opener(blocks[i])

    if not spec then
      if blocks[i].t == "Div" and has_comment_class(blocks[i]) then
        i = i + 1
      else
        out:insert(blocks[i])
        i = i + 1
      end
    else
      local inserted_before_open = false
      if before_open then
        out:insert(before_open)
        inserted_before_open = true
      end

      local j = i + 1
      local found = false
      local after_close_blocks = pandoc.List()

      if after_open then
        local is_close, _, after_close_candidate =
          strip_block_closer(after_open, spec.close)
        if is_close then
          found = true
          after_close_blocks = after_close_candidate
          j = i
        end
      end

      while (not found) and j <= n do
        local is_close, _, after_close_candidate =
          strip_block_closer(blocks[j], spec.close)
        if is_close then
          found = true
          after_close_blocks = after_close_candidate
          break
        end
        j = j + 1
      end

      if found then
        if inserted_before_open and #after_close_blocks > 0 then
          if para_like_t(out[#out]) and para_like_t(after_close_blocks[1]) then
            local merged_inlines = pandoc.List()
            for k = 1, #out[#out].content do
              merged_inlines:insert(out[#out].content[k])
            end
            if #merged_inlines > 0 then
              merged_inlines:insert(pandoc.Space())
            end
            for k = 1, #after_close_blocks[1].content do
              merged_inlines:insert(after_close_blocks[1].content[k])
            end
            out[#out] = clone_para_like(out[#out], merged_inlines)
            after_close_blocks:remove(1)
          end
        end

        for after_index = 1, #after_close_blocks do
          if not (
            after_close_blocks[after_index].t == "Div"
            and has_comment_class(after_close_blocks[after_index])
          ) then
            out:insert(after_close_blocks[after_index])
          end
        end
        i = j + 1
      else
        out:insert(blocks[i])
        i = i + 1
      end
    end
  end

  return out
end

function Div(el)
  if has_comment_class(el) then
    return {}
  end
end
