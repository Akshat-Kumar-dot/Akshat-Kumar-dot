# File tree banner: rule set

Design credit: FinnoTaylor's "literal file tree"
(https://x.com/FinnoTaylor/status/2112286571999428676). This is an independent
re-creation of the idea for a GitHub profile.

Measured from the reference video (1166×802,
window content ≈ 900×570). Values below are scaled to our 1196×614 content area.

## Pixels
- Everything organic is drawn on a grid of **4 px cells**, each painted as a
  **3 px dot** with a 1 px gap. That gap is what makes it read as pixel art.
- Edges are dithered: a cell on the edge of a branch or moss clump is drawn
  only some of the time, so outlines are ragged, never smooth.

## Branch shape
- Branches are grown, not drawn: a point walks forward 1 px at a time while its
  heading eases toward a target direction (mostly horizontal, to the right),
  plus a slow smooth wobble. Result: long arcs and gentle S-curves. No kinks,
  no straight spikes.
- A limb leaves its folder steeply (about 50° up or down) and bends to
  roughly horizontal within the first third of its length.
- Width (bark only): trunk 10 → 5 px, limb 8 → 3 px, twig 1 cell.
- Long limbs fork once (about 30°, two-thirds of the way along) and end in a
  small Y of dotted twigs. Side twigs are few, short, and lean forward along
  the growth direction (20–45° off the parent), never perpendicular.

## Branch colour (adapted to the dark #161B22 window)
- Upper edge: pale warm grey `#AAA294`.
- Core: warm grey `#8F8A80` with speckles of brown `#7A624E`, olive `#919553`,
  near-black `#28221F`, rust red `#96342A` and orange-brown `#B8763E`.
- Underside: dark brown `#4A3C34` / `#1E1917`.
- Twigs: dotted single cells in the core colours, with a lime or yellow cell
  at the tip.

## Moss
- Lime `#A6D628`, yellow-lime `#CDE83C`, yellow `#E8EC46`, green `#76AA20`,
  dark green `#467A22`, olive `#919553`.
- Moss gives branches their visual thickness: dense, dithered clumps wrapping
  the bark, mostly on the upper side.
- Density is highest at the base of a limb and fades along it, in patches
  with bare bark between them.

## Items
- A folder that gets opened sits at the **base of its own limb**; the limb
  grows out from behind the icon.
- Everything else floats in the space beside a branch, 45–110 px off it,
  usually near the end of a twig. Nothing is attached by a line.
- Items alternate sides along a limb, never overlap each other, and keep at
  least 18 px from any bark.
- Icons are thin light-grey outlines (folder ≈ 44×36 px, file page with a
  folded corner, with text lines for text files and blank for images).
  Labels use Inter Medium at 19 px, grey, to the right of the icon; folders
  that float (not yet opened) put the label underneath.
- The active item turns white: an opened folder switches to the open-folder
  icon.

## Motion
- The loop starts and ends on an empty window.
- The trunk grows in from the left. Bark draws first; moss follows about
  0.4 s behind it. Items fade in (0.3 s) as growth passes them.
- Opening a folder: its icon lights up, then its limb grows (bark about 1.1 s,
  moss after it) while the camera pans to frame the new limb and its
  contents. The parent branch slides out of view. The camera only moves
  sideways and up/down, never zooms, and eases in and out.
- Each project: open it, light up a few of its items one by one, open one
  of its subfolders the same way, then glide back to the trunk.
- When every project has been visited: hold, fade the window empty, loop.
- Title bar shows the current path; the footer shows how many items the
  current folder has.
