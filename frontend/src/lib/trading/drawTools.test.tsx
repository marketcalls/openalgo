import { registeredDrawingTools, DRAWING_TOOL_ICONS } from 'openalgo-charts/draw'
import { renderToStaticMarkup } from 'react-dom/server'
import { DRAW_GROUPS, drawToolIcon } from './drawTools'

describe('trading drawing catalogue', () => {
  const entries = DRAW_GROUPS.flatMap((group) => group.sections.flatMap((section) => section.tools))

  it('exposes each installed drawing tool exactly once', () => {
    expect(entries.map((tool) => tool.id).sort()).toEqual(
      registeredDrawingTools()
        .map((tool) => tool.id)
        .sort()
    )
  })

  it('uses the installed names and glyph paths for every menu entry', () => {
    for (const tool of registeredDrawingTools()) {
      const entry = entries.find((item) => item.id === tool.id)
      expect(entry, tool.id).toBeDefined()
      expect(entry?.label, tool.id).toBe(tool.name)
      const container = document.createElement('div')
      container.innerHTML = renderToStaticMarkup(drawToolIcon(entry!.iconKey))
      expect(container.querySelector('path')?.getAttribute('d'), tool.id).toBe(
        DRAWING_TOOL_ICONS[tool.id]
      )
    }
  })
})
