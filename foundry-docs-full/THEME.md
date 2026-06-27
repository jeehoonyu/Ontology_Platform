<table><tr>
<td style="background:#111418;color:#ffffff;padding:16px 22px;border-left:6px solid #2D72D2;font-size:15px">
<b style="color:#8ABBFF">PALANTIR · FOUNDRY DESIGN SYSTEM</b><br>
<span style="font-size:24px;color:#ffffff"><b>Color & UI Theme</b></span><br>
<span style="color:#ABB3BF">The palette every file in this folder uses — taken from Palantir's open-source <b>Blueprint</b> design system, which powers the Foundry product UI.</span>
</td></tr></table>

> **Why these colors?** Palantir's *brand* is intentionally just **black (#000000)** and **white (#FFFFFF)** with no accent. But the **Foundry product UI** is built on [**Blueprint**](https://blueprintjs.com/docs/) — Palantir's own React design system — whose palette below is the real, documented color system you see inside Workshop, Object Explorer, Contour, Map, and every other Foundry app. These files reproduce those colors using inline HTML so the swatches render in the VS Code Markdown preview.

## Semantic intents (how Foundry uses color)

<table>
<tr><th align="left">Intent</th><th align="left">Color</th><th align="left">Used for</th></tr>
<tr><td><span style="color:#2D72D2"><b>● Primary</b></span></td><td><code>#2D72D2</code> (Blue3)</td><td>Primary buttons, selected state, links, focus</td></tr>
<tr><td><span style="color:#238551"><b>● Success</b></span></td><td><code>#238551</code> (Green3)</td><td>Healthy builds, passed checks, confirmations</td></tr>
<tr><td><span style="color:#C87619"><b>● Warning</b></span></td><td><code>#C87619</code> (Orange3)</td><td>Stale data, pending approval, caution</td></tr>
<tr><td><span style="color:#CD4246"><b>● Danger</b></span></td><td><code>#CD4246</code> (Red3)</td><td>Failed builds, errors, destructive actions</td></tr>
</table>

## Surface & text (dark UI, the Foundry default)

<table>
<tr><td style="background:#111418;color:#fff;padding:8px 14px">App background — <code>#111418</code> (Black)</td></tr>
<tr><td style="background:#1C2127;color:#fff;padding:8px 14px">Panel / card — <code>#1C2127</code> (Dark Gray 1)</td></tr>
<tr><td style="background:#252A31;color:#fff;padding:8px 14px">Raised element — <code>#252A31</code> (Dark Gray 2)</td></tr>
<tr><td style="background:#383E47;color:#fff;padding:8px 14px">Border / divider — <code>#383E47</code> (Dark Gray 4)</td></tr>
<tr><td style="background:#ABB3BF;color:#111418;padding:8px 14px">Muted text — <code>#ABB3BF</code> (Gray 4)</td></tr>
<tr><td style="background:#F6F7F9;color:#111418;padding:8px 14px">Light-mode background — <code>#F6F7F9</code> (Light Gray 5)</td></tr>
</table>

## Full Blueprint palette (name → hex)

**Grayscale**

| Name | Hex | Name | Hex |
|---|---|---|---|
| Black | `#111418` | Light Gray 1 | `#D3D8DE` |
| Dark Gray 1 | `#1C2127` | Light Gray 2 | `#DCE0E5` |
| Dark Gray 2 | `#252A31` | Light Gray 3 | `#E5E8EB` |
| Dark Gray 3 | `#2F343C` | Light Gray 4 | `#EDEFF2` |
| Dark Gray 4 | `#383E47` | Light Gray 5 | `#F6F7F9` |
| Dark Gray 5 | `#404854` | White | `#FFFFFF` |
| Gray 1 | `#5F6B7C` | Gray 2 | `#738091` |
| Gray 3 | `#8F99A8` | Gray 4 | `#ABB3BF` |
| Gray 5 | `#C5CBD3` | | |

**Core colors** (shades 1→5, dark→light)

| Hue | 1 | 2 | 3 (intent) | 4 | 5 |
|---|---|---|---|---|---|
| <span style="color:#4C90F0">Blue</span> | `#184A90` | `#215DB0` | `#2D72D2` | `#4C90F0` | `#8ABBFF` |
| <span style="color:#32A467">Green</span> | `#165A36` | `#1C6E42` | `#238551` | `#32A467` | `#72CA9B` |
| <span style="color:#EC9A3C">Orange</span> | `#77450D` | `#935610` | `#C87619` | `#EC9A3C` | `#FBB360` |
| <span style="color:#E76A6E">Red</span> | `#8E292C` | `#AC2F33` | `#CD4246` | `#E76A6E` | `#FA999C` |

**Extended colors** (3-shade, used for charts, markers, map layers)

| Hue | Hex (shade 3) | Hue | Hex (shade 3) |
|---|---|---|---|
| <span style="color:#147EB3">Cerulean</span> | `#147EB3` | <span style="color:#00A396">Turquoise</span> | `#00A396` |
| <span style="color:#29A634">Forest</span> | `#29A634` | <span style="color:#8EB125">Lime</span> | `#8EB125` |
| <span style="color:#D1980B">Gold</span> | `#D1980B` | <span style="color:#946638">Sepia</span> | `#946638` |
| <span style="color:#D33D17">Vermilion</span> | `#D33D17` | <span style="color:#DB2C6F">Rose</span> | `#DB2C6F` |
| <span style="color:#9D3F9D">Violet</span> | `#9D3F9D` | <span style="color:#7961DB">Indigo</span> | `#7961DB` |

## Banner snippet used at the top of every file

```html
<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · CATEGORY</b><br>
<span style="font-size:22px"><b>Tool Name</b></span><br>
<span style="color:#ABB3BF">one-line definition</span>
</td></tr></table>
```

---
Sources: [Blueprint colors source (`palantir/blueprint`)](https://github.com/palantir/blueprint/blob/develop/packages/colors/src/colors.ts) · [Blueprint docs](https://blueprintjs.com/docs/) · [Foundry Workshop “Used colors”](https://www.palantir.com/docs/foundry/workshop/used-colors)
