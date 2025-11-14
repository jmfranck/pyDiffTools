-- obs.lua

-- Process custom <obs> tags. These appear in the input as RawInline elements
-- for the opening and closing tags. The content between them should continue to
-- be parsed as normal markdown. This filter converts:
--   <obs author="NAME" date="DATE">content</obs>
-- into a span containing the author/date (smaller and green) followed by the
-- content colored blue.

local function parse_attrs(attr)
  local author = attr:match('author="([^"]+)"')
  local when = attr:match('time="([^"]+)"') or attr:match('date="([^"]+)"')
  return author, when
end

function Inlines(inls)
  local out = {}
  local i = 1
  while i <= #inls do
    local el = inls[i]
    if el.t == 'RawInline' and el.format == 'html' then
      local attr = el.text:match('^<obs%s+([^>]+)>$')
      if attr then
        -- gather inner content up to the closing tag
        local inner = {}
        local j = i + 1
        while j <= #inls do
          local cur = inls[j]
          if cur.t == 'RawInline' and cur.format == 'html' and cur.text:match('^</obs>$') then
            break
          else
            table.insert(inner, cur)
          end
          j = j + 1
        end
        if j <= #inls then
          local author, when = parse_attrs(attr)
          local prefix_parts = {}
          if when then table.insert(prefix_parts, when) end
          if author then table.insert(prefix_parts, author) end
          local prefix = nil
          if #prefix_parts > 0 then
            local txt = table.concat(prefix_parts, ' ') .. ':'
            prefix = pandoc.Span(
              { pandoc.Str(txt) },
              pandoc.Attr('', {}, { style = 'font-size:85%; color:green;' })
            )
          end
          local body = pandoc.Span(
            pandoc.List(inner),
            pandoc.Attr('', {}, { style = 'color:blue;' })
          )
          if prefix then
            table.insert(out, prefix)
            table.insert(out, pandoc.Space())
          end
          table.insert(out, body)
          i = j + 1
          goto continue
        end
      elseif el.text == '<obs>' then
        -- simple <obs> with no attributes
        local inner = {}
        local j = i + 1
        while j <= #inls do
          local cur = inls[j]
          if cur.t == 'RawInline' and cur.format == 'html' and cur.text:match('^</obs>$') then
            break
          else
            table.insert(inner, cur)
          end
          j = j + 1
        end
        if j <= #inls then
          local body = pandoc.Span(
            pandoc.List(inner),
            pandoc.Attr('', {}, { style = 'color:blue;' })
          )
          table.insert(out, body)
          i = j + 1
          goto continue
        end
      end
    end
    table.insert(out, el)
    i = i + 1
    ::continue::
  end
  return out
end

-- Convert <err>...</err> blocks spanning multiple paragraphs into a styled Div
function Blocks(blocks)
  local out = pandoc.List{}
  local stack = {}

  local function current_container()
    if #stack > 0 then
      return stack[#stack].content
    else
      return out
    end
  end

  local function start_err()
    table.insert(stack, {content = pandoc.List{}})
  end

  local function finish_err()
    local entry = table.remove(stack)
    if not entry then
      return
    end
    local header = pandoc.Para({
      pandoc.Span({pandoc.Str('DEBUG:')}, pandoc.Attr('', {}, {style = 'color:grey;'}))
    })
    local body = pandoc.Div(entry.content, pandoc.Attr('', {}, {style = 'margin:10px; border:0px;'}))
    local div = pandoc.Div({header, body}, pandoc.Attr('', {}, {style = 'margin:0px; border:1px solid grey; padding:0px;'}))
    current_container():insert(div)
  end

  for _, blk in ipairs(blocks) do
    if blk.t == 'Para' then
      local buffer = pandoc.List{}
      for _, inline in ipairs(blk.content) do
        if inline.t == 'RawInline' and inline.format == 'html' and inline.text == '<err>' then
          if #buffer > 0 then
            current_container():insert(pandoc.Para(buffer))
            buffer = pandoc.List{}
          end
          start_err()
        elseif inline.t == 'RawInline' and inline.format == 'html' and inline.text == '</err>' then
          if #buffer > 0 then
            stack[#stack].content:insert(pandoc.Para(buffer))
            buffer = pandoc.List{}
          end
          finish_err()
        else
          buffer:insert(inline)
        end
      end
      if #buffer > 0 then
        current_container():insert(pandoc.Para(buffer))
      end
    else
      current_container():insert(blk)
    end
  end

  return out
end

