# Assetto Corsa track maker

Draw a race track in your browser, then let Blender turn it into a driveable [Assetto Corsa](https://store.steampowered.com/app/244210/Assetto_Corsa/) circuit with road, kerbs, run-off, walls, terrain, pits and all the markers the game needs.

**New here? Follow [GUIDE.md](GUIDE.md).** It walks through every step from drawing a layout to driving it.

## What's in it

**Track designer** (`designer/track-designer.html`): a single web page that runs offline in Chrome or Edge.

- Drag points to shape the track, and draw elevation in the profile chart.
- Banking up to 45°, with an option to keep banked turns as wide as the straights seen from above.
- Auto-smooth banking: average, keep the highest or keep the lowest angles.
- Select several points at once to raise, lower or bank them together.
- Separate outside and infield run-off, kerbs, gravel traps, and up to 60 pit boxes and grid slots.
- Live checks for overlaps, too-tight corners, steep slopes and banking that changes too quickly.
- Metric or imperial units.
- **Real tracks menu**: 67 layouts used by NASCAR, INDYCAR, IMSA and F1. Shapes are traced from OpenStreetMap, elevation comes from terrain survey data and ovals get their published banking.

**Builder** (`builder/build_track.py`, run by `build_track.bat`): a Blender script that turns a saved `.layout.json` into:

- an FBX with textures, ready for Kunos' ksEditor to convert into a `.kn5`
- a `.blend` file to decorate further
- the Assetto Corsa track folder: `ui_track.json`, map, outline, preview, `surfaces.ini`, cameras and lighting, plus Custom Shaders Patch grass settings

**Installer** (`install_track.bat`): copies finished tracks into Assetto Corsa's `content\tracks` folder.

## Requirements

- Windows, with Chrome or Edge for the designer
- [Blender](https://www.blender.org/) (tested with 5.2), installed under `C:\Program Files\Blender Foundation`
- Assetto Corsa with its SDK (`sdk\editor\ksEditor.exe` is in the game folder)
- Content Manager and Custom Shaders Patch are recommended

`install_track.bat` expects the game at `D:\SteamLibrary\steamapps\common\assettocorsa`. Edit the path at the top of the file if yours is elsewhere.

## Quick start

1. Open `designer/track-designer.html`, shape a track (or pick one from **Real tracks…**) and click **Save layout**.
2. Drag the saved `.layout.json` onto `build_track.bat`.
3. In ksEditor, load `output/<id>/fbx/<id>.fbx` and save it as a track `.kn5` in `output/<id>/track/<id>/`.
4. Run `install_track.bat`, then pick the track in Content Manager.

`examples/` has ready-made layouts to try.

## Folders

| Folder | Contents |
|---|---|
| `designer/` | The track designer page |
| `builder/` | Blender builder and `layout_core.py`, a Python copy of the designer's track maths |
| `examples/` | Example layouts |
| `tools/` | Scripts that generate the designer's real-track library |
| `output/` | Built tracks (not stored in git: rebuild them from a layout) |

## Rebuilding the real-track library

Only needed to add or fix real tracks. Each script's usage is at the top of the file. They need a Python with numpy, and Blender's bundled Python works.

1. `tools/track_catalog.py`: the list of tracks, with official lengths, banking and options.
2. `tools/osm_fetch.py`: downloads OpenStreetMap data for each venue into a cache folder.
3. `tools/osm_import.py`: finds each layout in that data, fits designer points, adds elevation (`tools/elevation.py`) and banking, and writes a library file and a report.
4. `tools/inject_library.py`: pastes the library into the designer page.

`tools/contact_png.py` draws every layout on one sheet for a quick visual check.

## Data and credits

- Track shapes © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, available under the Open Database License. Keep this credit on any track you share that was built from the real-tracks menu.
- Elevation from [OpenTopoData](https://www.opentopodata.org/), using USGS NED (USA), EU-DEM (Europe) and SRTM (elsewhere).
- Assetto Corsa and ksEditor are by Kunos Simulazioni. This project is not affiliated with Kunos, or with any circuit or racing series named in the track list.
