# Making your own Assetto Corsa track

This folder turns a track you draw in your browser into a driveable Assetto Corsa circuit.

```
designer\track-designer.html   1. draw the layout, save a .layout.json
build_track.bat                2. drag the .layout.json onto this, Blender builds the 3D track
  output\<id>\fbx\             3. open the FBX in ksEditor, save it as a .kn5
  output\<id>\track\<id>\      the finished track folder (ui, data, map...)
install_track.bat              4. copies finished tracks into Assetto Corsa
examples\                      ready-made layouts to try
builder\                       the Blender scripts (you don't need to open these)
```

---

## Step 1: Design the layout

1. Double-click `designer\track-designer.html`. It opens in Chrome or Edge.
2. It starts with a **Starter circuit**. Shape it however you like:
   - drag the white points to move the track
   - double-click the road to add a point, right-click a point to delete it
   - drag the dots in the **Elevation** chart up and down to make hills
   - click a point in a corner and raise **Banking** to tilt it (up to 45°; give steep banking a few points to build up gradually)
   - **Banked turns as wide as the straights** (on by default) keeps the road the same width seen from above. Banked sections are tilted, so their surface is a bit wider: a 20 m road on 38° banking measures 25.4 m across the tilted surface. Turn it off if you want the road width measured across the surface instead, as real tracks quote it. Steep turns then look narrower from above (15.8 m for that 20 m road at 38°). The map always shows the real top-down width.
   - **Auto-smooth banking** makes the banking build up and ease off gradually, instead of point to point. Pick how:
     - **Average** blends each spot with its neighbours, so the steepest parts come down a little and the flattest come up.
     - **Keep highest** never lowers the banking: steep turns keep their full angle and the build-up starts earlier.
     - **Keep lowest** never raises it: flatter parts keep their angle and the build-up starts later.

     **Smoothing distance** is how long the build-up takes. Your points keep the angles you typed. When a point is selected, the panel also shows "After auto-smooth" with the angle the road actually gets there. Where the road switches from leaning one way to the other (an S-bend banked both ways), the banking passes through flat, so Keep highest lowers it slightly right at the switch.
   - to change a whole stretch at once, select several points: **Ctrl+click** them one by one, **Shift+click** to take every point between the last one and this one, or hold **Shift** and drag a box around them (**Ctrl+A** selects all). This works on the map and on the Elevation chart. The panel then has two sets of buttons:
     - **Elevation**: −/+ buttons (5 m and 1 m, or 10 ft and 1 ft) raise or lower every selected point by the same amount, so hills keep their shape. **Set all to** puts them all at one height, which makes that stretch level.
     - **Banking**: **−5° −1° +1° +5°** change every selected point by the same amount, and **Set all to** gives them one angle. If the points don't all have the same banking, a yellow note says so and lists each point's angle.
     - **Del** removes every selected point.
   - **Blank** in "Start from" lets you click out a layout from scratch, point by point, in driving order
   - **Real tracks…** in "Start from" is a menu of real circuits used by NASCAR, INDYCAR, IMSA and F1, grouped by series. Each one's shape is traced from OpenStreetMap, its hills come from terrain survey data (10 m resolution in the USA, 25 m in Europe, 30 m elsewhere), ovals get their published banking, and the start line and pits sit where the real ones are. They come with generic walls, kerbs and run-off rather than the real surroundings. Elevation is smoothed, so small bumps aren't there; Singapore and Mexico City are kept flat because the survey data there is unreliable. If you share a track built from one, credit "© OpenStreetMap contributors".
   - **Outside run-off** and **Infield run-off** set how far the walls are from the edge of the road on each side. **0** puts the wall right against the road, like a superspeedway. Kerbs are left out wherever the wall is too close for them. The pit area always keeps room for its pit lane, and the wall steps out just before it.
   - **Wall height** goes from 0.5 m to 10 m (1.2 m by default). Tall walls stop cars flying out of a fast banked oval. The TV cameras are placed above the walls.
   - **Pit boxes / grid slots** goes up to 60. Above 24 cars, the pit boxes go in two rows side by side, where the apron is wide enough, so the pit area stays a sensible length.
3. Keep an eye on **Checks** in the right panel. Red items must be fixed before building; amber ones are advice.
4. Rename the track by clicking its name at the top left, and add your name under **File → Author**.
5. Click **Save layout**. The file lands in your Downloads folder (`D:\DOWNLOADS`) as `<track_name>.layout.json`.

Your work is autosaved in the browser, so you can close the page and come back.

**Metric / Imperial** at the top right switches everything on screen between metres/kilometres and feet/miles. It only changes what's shown: saved layout files and the Blender build always use metres, so you can switch at any time.

## Step 2: Build the 3D track

Drag the `.layout.json` file onto **`build_track.bat`**. A black window opens, Blender runs in the background for a few seconds, and you get:

| Folder | What it's for |
|---|---|
| `output\<id>\fbx\<id>.fbx` + `texture\` | The model for ksEditor (step 3) |
| `output\<id>\blender\<id>.blend` | The same track in Blender, if you want to add buildings, trees and so on |
| `output\<id>\track\<id>\` | The Assetto Corsa track folder. Only the `.kn5` is missing. |

`<id>` is the track name in lower case with underscores, for example `starter_circuit`.

What gets built: asphalt with white edge lines, red/white kerbs on corners, grass, gravel traps on the outside of fast corners, a concrete pit area beside the grid, concrete walls, rolling terrain beyond the walls, a chequered start line, grid boxes, and all the invisible markers Assetto Corsa needs (grid spots, pit boxes, hotlap start, timing gates).

## Step 3: Make the .kn5 in ksEditor

The `.kn5` is Assetto Corsa's model format. Kunos' own editor makes it:

1. Open `D:\SteamLibrary\steamapps\common\assettocorsa\sdk\editor\ksEditor.exe`.
2. From the **File** menu, load/import the FBX: `output\<id>\fbx\<id>.fbx`.
3. The track should appear with its textures. If a surface looks white or black, open the **Materials** list, pick that material, set its shader to `ksPerPixel` and set `txDiffuse` to the matching PNG in the `texture` folder.
4. From the **File** menu choose **Save kn5**, pick the **track** option (not car), and save it as
   `output\<id>\track\<id>\<id>.kn5`. The file name must match the folder name.

> Claude hasn't been able to click through ksEditor itself, so the menu wording may differ slightly. If anything doesn't match, describe what you see.

## Step 4: Install and drive

1. Double-click **`install_track.bat`**. It copies every track that has its `.kn5` into
   `D:\SteamLibrary\steamapps\common\assettocorsa\content\tracks\`.
2. Open Content Manager → **Drive** → **Practice**, pick your track and go.

## If something's not right

| Problem | Fix |
|---|---|
| Car starts facing backwards | Rebuild with the spawn points flipped: run `build_track.bat` from a terminal with `--flip-spawns` after the layout path, then redo steps 3–4. |
| Car falls through the world | The physical objects must keep their names (`1ROAD`, `2GRASS`, `1KERB`...). Don't rename them in ksEditor. |
| Track missing in Content Manager | The `.kn5` must be named exactly like its folder, e.g. `starter_circuit\starter_circuit.kn5`. |
| No AI opponents, no TV cameras in replays | Both need an AI line. That's the next step (below). |

## Changing the track later

Edit the layout in the designer → **Save layout** → drag it onto `build_track.bat` → load the FBX in ksEditor again and save over the old `.kn5` → `install_track.bat`.

## Saving your work to GitHub

This folder is backed up to a private GitHub repository: https://github.com/FDJoss/acmapping. Built tracks in `output\` aren't uploaded (they're big, and `build_track.bat` can remake them from a layout).

After changing something, open a terminal in this folder and run:

```
git add -A
git commit -m "Say what you changed"
git push
```

If Windows says `git` isn't recognised, close and reopen the terminal (or the Claude app) so it picks up the newly installed Git.

## Coming next

- **AI line**: drive one clean lap with the recorder running, so AI cars can race and replay cameras work.
- **Decoration**: trees, grandstands, a pit building and signs, added in the `.blend`.
- **Proper preview image**: a screenshot from the game to replace the generated `ui\preview.png`.
