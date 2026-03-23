# RetroFE Theme Browser Findings

## Scope
- Analyzed `V:\base_assets\layouts`
- Found 14 top-level themes
- Analyzed 453 active `layout.xml` files
- Breakdown: 14 theme root layouts and 439 collection override layouts
- Also found 14 `splash.xml` files
- Ignored historical/alternate XMLs for spec purposes: 78 `layoutold.xml`, 3 `layoutbackup*.xml`, 3 `layout1.xml`

## Theme Coverage
- Root only plus `_common` media: `NEVATO`
- Root plus `Jukebox` override: `Amiga Memories`, `Atari Girl`, `Beavis and Butt-Head`, `Fan Art Magazine`, `Live Wallpapers`, `Old Memories`, `Pacman`, `Princess Power`
- Small curated override sets:
  - `CoinOPS`: 6 collection layouts
  - `Renee`: 11 collection layouts
- Large override sets:
  - `Cyberpunkd`: 123 collection layouts
  - `Cafe80s`: 127 collection layouts
  - `LUNA OG`: 164 collection layouts

## Effective Folder Shape
- `<theme>\layout.xml`
- `<theme>\splash.xml`
- `<theme>\collections\_common\medium_artwork\<slot>\...`
- `<theme>\collections\<CollectionName>\layout\layout.xml`
- `<theme>\collections\<CollectionName>\system_artwork\...`
- Collection folder names track the application collection names in `V:\base_assets\collections`, including category/group collections such as `1 ARCADES`, `2 ARCADE GENRES`, `THEMES`, `Jukebox`, `Light Gun`, `Trackball`, and `Twin Stick`

## RetroFE Layout XML: Draft Spec
- Root node is `<layout>`
- Common root attributes: `width`, `height`, `font`, `loadFontSize`, `fontColor`
- Almost every layout targets `1920x1080`
- Positioning is absolute and uses anchors like `left`, `right`, `center`, `top`, `bottom`, plus `xOrigin` and `yOrigin`
- Layering is manual via `layer`; comments often define per-theme layer meaning, so layer numbers are theme-local conventions rather than global rules

### Core Element Types
- Static: `<image>`, `<video>`, `<text>`, `<sound>`
- Dynamic/reloadable: `<reloadableImage>`, `<reloadableVideo>`, `<reloadableText>`, `<reloadableScrollingText>`
- Menu model: `<menu>`, `<itemDefaults>`, `<item>`
- Animation model: `<set>`, `<animate>`
- Less common but valid in these themes: `<scrollingText>`

### Observed Usage Volume
- `<image>`: 3586
- `<reloadableImage>`: 2689
- `<text>`: 1842
- `<reloadableText>`: 1997
- `<reloadableVideo>`: 458
- `<reloadableScrollingText>`: 420
- `<scrollingText>`: 136
- `<menu>`: 577
- `<sound>`: 937

### Menu Model
- Menus are almost always `type="custom"`
- Observed orientations: `horizontal`, `vertical`
- Common menu `imageType` values: `logo`, `artwork_front`, `artwork_front_s`
- `<itemDefaults>` provides baseline geometry/text/media behavior
- `<item>` defines wheel positions, offsets, alpha, angle, and the selected item
- Some layouts define multiple menus for multi-level navigation or alternate wheel sections

### Dynamic Media/Text Sources
Observed `type`/source concepts include:
- Collection counters: `collectionIndex`, `collectionSize`
- Clock/info: `time`, `playlist`
- Metadata text: `title`, `story`, `genre`, `year`
- Shared artwork slots: `firstLetter`, `manufacturer`, `score`, `ctrlType`, `numberButtons`, `numberPlayers`, `rightStrip`
- System artwork slots: `logo`, `device`, `display`, `background`
- Theme-family-specific artwork slots:
  - `LUNA OG`: `MainBackground`, `MainCharacter`, `ExtraCharacter`, `MainConsole`, `MainLogo`, `eplogo`, `eptop`

### Mode Semantics
This is an inference from the folder structure and usage patterns:
- `mode="layout"`: resolve from the active theme or collection layout context
- `mode="systemlayout"`: resolve from `collections\<CollectionName>\system_artwork`
- `mode="commonlayout"`: resolve from `collections\_common\medium_artwork`
- `mode="common"` appears in some `Cafe80s` files and should be treated as a variant/alias rather than a hard failure

### Event Hooks
Common event nodes observed:
- `onEnter`, `onExit`, `onIdle`
- `onMenuEnter`, `onMenuExit`, `onMenuScroll`, `onMenuIdle`
- `onHighlightEnter`, `onHighlightExit`
- `onJumpEnter`
- `onMenuJumpEnter`, `onMenuJumpExit`
- `onPlaylistEnter`, `onPlaylistExit`
- `onPlaylistJumpEnter`, `onPlaylistJumpExit`

### Animation Properties
Common animated properties:
- `x`, `y`
- `xOffset`, `yOffset`
- `alpha`
- `width`, `height`
- `volume`
- `nop`

## Shared `_common` Artwork Slots
Observed shared slot folders include:
- `firstLetter`
- `isFavorite`
- `playlist`
- `rightStrip`
- `cabinet`
- `neon`
- `ctrlType`
- `manufacturer`
- `numberButtons`
- `numberPlayers`
- `score`

## Theme Family Notes
- `LUNA OG` is the most complete “system detail” family. It uses large per-system `system_artwork` sets and rich metadata overlays.
- `Cafe80s` uses a strong “cabinet/jumbotron” pattern with device art, system logos, playlist banners, and metadata callouts.
- `Cyberpunkd` uses more background/device/display/logo combinations and genre/category-specific color/background variations.
- `CoinOPS` and some `Renee` layouts use multiple menu blocks, which suggests hierarchical or alternate wheel presentations.
- The simpler themes mostly depend on the root `layout.xml` and optionally a dedicated `Jukebox` collection override.

## Parser/Browser Recommendations
- Treat `layout.xml` as the effective theme definition
- Ignore `layoutold.xml`, backup XMLs, and `layout1.xml` unless a “history/variants” view is desired
- Normalize tag names and attribute names case-insensitively when indexing themes
- Do not fail on unknown nodes, attributes, or event names
- Index each theme with:
  - theme name
  - root layout path
  - splash presence
  - collection override count
  - supported collection names
  - `_common` artwork slots
  - per-collection `system_artwork` slot names
  - menu orientations and menu count
  - notable anomalies

## Important Anomalies
- Attribute casing is inconsistent: `loadFontSize` vs `loadfontSize`
- Fallback attribute casing is inconsistent: `textFallback` vs `textFallBack`
- Size attribute casing is inconsistent: `maxWidth` vs `maxwidth`
- Mixed-case tag appears: `Reloadableimage`
- Rare/nonstandard event name appears: `onMenuJumpEntrance`
- Browser/parser should be permissive and normalization-based, not strict-schema-based
