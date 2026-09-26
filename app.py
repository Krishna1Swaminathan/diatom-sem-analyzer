"""Diatom Analyzer: count and measure diatoms in SEM images, step by step.

Start it by double-clicking "Start Diatom Analyzer" (see README), or run:  streamlit run app.py
"""

import io
import tempfile
import zipfile
from pathlib import Path

import altair as alt
import cv2
import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image
from streamlit_image_coordinates import streamlit_image_coordinates

from diatom_analyzer import __version__
from diatom_analyzer.calibration import ocr_available
from diatom_analyzer.classification import IMAGE_SUFFIXES, SpeciesLibrary
from diatom_analyzer.config import AnalysisConfig
from diatom_analyzer.editing import save_training_example
from diatom_analyzer.evaluate import build_library
from diatom_analyzer.export import frustule_rows, pore_rows, write_excel
from diatom_analyzer.pipeline import analyze_image
from diatom_analyzer.visualize import DAMAGE_COLORS, PORE_COLOR, render_overlay

HERE = Path(__file__).parent
DEMO_DIR = HERE / "sample_data"
DEFAULT_LIBRARY = HERE / "species_library"
MODELS_DIR = HERE / "models"
UNITS = {"nm": 1e-3, "µm": 1.0, "mm": 1e3}
SERIES_BLUE = "#2a78d6"

# Everyday words for the values the analysis produces.
CONDITION = {"intact": "Intact", "cracked": "Cracked", "fragmented": "Broken",
             "uncertain": "Cut off at image edge", "not graded": "Not assessed"}
SHAPE = {"centric": "Round (centric)", "pennate (elliptic)": "Elongated (pennate)",
         "pennate (linear)": "Long and narrow (pennate)", "girdle view": "Seen from the side",
         "fragment": "Broken piece"}
SCALE_SOURCE = {"metadata": "from the microscope's file", "scale_bar": "read from the scale bar in the image",
                "tick ruler": "read from the scale ruler in the image", "manual": "entered by you",
                "databar": "read from the information strip"}

SAMPLE_TYPES = {
    "apart": ("Diatoms lying apart from each other",
              "A fairly clean background; most diatoms don't touch."),
    "round": ("Many small round cells packed together",
              "Cultures of round (centric) diatoms, such as Thalassiosira."),
    "manual": ("Crowded or messy: I will point out the diatoms myself",
               "Nothing is found automatically. In step 3 you mark each diatom."),
    "model": ("Use the lab's trained model",
              "A detection model trained on this lab's own images."),
}

st.set_page_config(page_title="Diatom Analyzer", page_icon="🔬", layout="wide",
                   initial_sidebar_state="collapsed")

state = st.session_state
state.setdefault("overrides", {})  # image name -> scale corrections
state.setdefault("use_demo", False)
state.setdefault("edits", {})  # image name -> list of manual corrections
state.setdefault("last_click", {})  # image name -> timestamp of the last click already applied


# --------------------------------------------------------------------------- helpers


def build_config(s):
    cfg = AnalysisConfig()
    cfg.segmentation.method = s["method"]
    cfg.segmentation.cell_diameter_um = tuple(s["cell_diameter"])
    cfg.segmentation.cell_roundness = s["cell_roundness"]
    cfg.segmentation.cellpose_model = s.get("cellpose_model", "")
    cfg.segmentation.min_frustule_um = s["min_size_um"]
    cfg.segmentation.split_touching = s["split"]
    cfg.pores.min_diameter_um, cfg.pores.max_diameter_um = s["pore_range"]
    cfg.pores.contrast_k = s["pore_sensitivity"]
    cfg.damage.fragment_corner_deg = s["frag_corner"]
    cfg.damage.fragmented_solidity = s["frag_solidity"]
    return cfg


def library_signature(folder):
    folder = Path(folder)
    if not folder.exists():
        return ()
    return tuple(sorted((str(p), p.stat().st_mtime) for p in folder.rglob("*") if p.is_file()))


@st.cache_data(show_spinner=False, max_entries=64)
def run_analysis(data, name, settings, manual_um, manual_bar_um, databar_top, library_dir, _lib_sig,
                 sidecar_text=None, edits=()):
    library = SpeciesLibrary(library_dir) if _lib_sig else None
    return analyze_image(data, name=name, config=build_config(dict(settings)), manual_um_per_px=manual_um,
                         manual_bar_um=manual_bar_um, library=library, databar_top=databar_top,
                         sidecar_text=sidecar_text, edits=edits)


def trained_models():
    if not MODELS_DIR.exists():
        return []
    return sorted(p for p in MODELS_DIR.iterdir() if p.is_file() and p.suffix == "")


def histogram(values, label):
    df = pd.DataFrame({"value": values})
    return (
        alt.Chart(df)
        .mark_bar(color=SERIES_BLUE, cornerRadiusTopLeft=4, cornerRadiusTopRight=4, binSpacing=2)
        .encode(
            x=alt.X("value:Q", bin=alt.Bin(maxbins=30), title=label),
            y=alt.Y("count()", title="Number of diatoms" if "Length" in label else "Number of pores"),
            tooltip=[alt.Tooltip("value:Q", bin=alt.Bin(maxbins=30), title=label, format=".3g"),
                     alt.Tooltip("count()", title="Count")],
        )
        .properties(height=240)
        .configure_axis(gridOpacity=0.35, domainOpacity=0.4)
    )


def legend_html():
    labels = {**CONDITION, "uncertain": "Cut off at edge, or not assessed"}
    chips = []
    for key, (r, g, b) in DAMAGE_COLORS.items():
        chips.append(f"<span style='display:inline-flex;align-items:center;margin-right:16px'>"
                     f"<span style='width:14px;height:14px;border-radius:3px;background:rgb({r},{g},{b});"
                     f"display:inline-block;margin-right:6px'></span>{labels[key]}</span>")
    r, g, b = PORE_COLOR
    chips.append(f"<span style='display:inline-flex;align-items:center'><span style='width:14px;height:14px;"
                 f"border-radius:50%;border:2px solid rgb({r},{g},{b});display:inline-block;margin-right:6px'>"
                 f"</span>Pore</span>")
    return "<div style='font-size:0.95rem;line-height:1.9'>Outline colours: " + "".join(chips) + "</div>"


def png_bytes(rgb):
    ok, buf = cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    return buf.tobytes()


def scale_sentence(cal):
    if not cal.ok:
        return None
    nm = cal.um_per_px * 1000
    size = f"{nm:.3g} nm" if nm < 1000 else f"{cal.um_per_px:.3g} µm"
    source = next((text for key, text in SCALE_SOURCE.items() if cal.source.startswith(key)), cal.source)
    return f"1 pixel = {size} ({source})"


def friendly_table(res):
    rows = pd.DataFrame(frustule_rows(res))
    if rows.empty:
        return rows
    out = pd.DataFrame({
        "No.": rows["frustule_id"],
        "Condition": rows["damage"].map(CONDITION).fillna(rows["damage"]),
        "Shape": rows["morphotype"].map(SHAPE).fillna(rows["morphotype"]),
    })
    if rows["species"].fillna("").astype(bool).any():
        out["Species"] = rows["species"].replace({"unknown": "not sure"})
    out["Length (µm)"] = rows["length_um"]
    out["Width (µm)"] = rows["width_um"]
    out["Pores"] = rows["pore_count"]
    out["Average pore size (µm)"] = rows["pore_mean_diameter_um"]
    if (rows["origin"] == "manual").any():
        out["Marked by"] = rows["origin"].map({"manual": "you", "auto": "tool"})
    return out


# --------------------------------------------------------------------------- expert settings (sidebar)

with st.sidebar:
    st.header("Expert settings")
    st.caption("You don't need to change anything here. These are for fine-tuning.")

    st.subheader("Scale")
    scale_mode = st.radio("Scale for all images",
                          ["Automatic", "The scale bar in every image shows…", "Pixel size of every image is…"],
                          help="Automatic reads the pixel size stored in the file by the microscope, or finds the "
                               "scale bar and reads its label. The pixel size is never assumed.")
    global_um, global_bar = None, None
    if scale_mode.startswith("The scale bar"):
        c1, c2 = st.columns([2, 1])
        value = c1.number_input("Length", min_value=0.0, value=10.0, step=1.0)
        unit = c2.selectbox("Unit", list(UNITS), index=1)
        global_bar = value * UNITS[unit] if value > 0 else None
    elif scale_mode.startswith("Pixel size"):
        global_um = st.number_input("µm per pixel", min_value=0.0, value=0.0, step=0.001, format="%.5f") or None
    if not ocr_available():
        st.info("Text reading (Tesseract) isn't installed, so scale bars can't be read automatically. Files "
                "with microscope metadata still work; otherwise you'll be asked what the scale bar says.")

    st.subheader("Finding diatoms")
    min_size = st.number_input("Ignore objects smaller than (µm)", 0.1, 500.0, 3.0, 0.5)
    split = st.checkbox("Separate diatoms that touch", value=True)
    roundness = st.slider("Round cells: how complete a rim must be", 0.3, 0.95, 0.5, 0.05,
                          help="Lower finds partly hidden or tilted cells but may add false circles.")

    st.subheader("Pores")
    pore_range = st.slider("Pore size range (µm)", 0.01, 10.0, (0.03, 4.0), 0.01)
    pore_sensitivity = st.slider("Pore detection strictness", 0.2, 1.5, 0.5, 0.05,
                                 help="Lower finds fainter pores; higher keeps only clear ones.")

    st.subheader("Damage grading")
    frag_corner = st.slider("Broken if the outline has a sharp inward corner above (°)", 20, 90, 40, 1,
                            help="Broken edges meet the natural outline at sharp inward corners; intact "
                                 "outlines curve smoothly.")
    frag_solidity = st.slider("Broken if solidity below", 0.5, 0.95, 0.85, 0.01,
                              help="Solidity = outline area / area of its convex hull.")

    st.subheader("Folders")
    library_dir = st.text_input("Species library folder", value=str(DEFAULT_LIBRARY))
    train_dir = st.text_input("Training examples folder", value=str(HERE / "training_data"))
    st.caption(f"Diatom Analyzer v{__version__} · open source · runs on this computer only")

lib_sig = library_signature(library_dir)
library = SpeciesLibrary(library_dir)


# --------------------------------------------------------------------------- header + step 1

st.title("🔬 Diatom Analyzer")
st.markdown("Count and measure the diatoms in scanning-electron-microscope images. "
            "Your images stay on this computer.")

st.subheader("1 · Add your images")
uploads = st.file_uploader(
    "Drag SEM images here, or click *Browse files*. TIF, JPG and PNG all work.",
    type=[s.strip(".") for s in IMAGE_SUFFIXES] + ["txt"], accept_multiple_files=True,
    help="If the microscope saved a .txt file next to each image (Hitachi, JEOL), add those files too: "
         "they tell the tool the exact scale.")
demo_files = sorted(p for p in DEMO_DIR.glob("*") if p.suffix.lower() in IMAGE_SUFFIXES)
if state.use_demo:
    c1, c2 = st.columns([3, 1])
    c1.info("Using the example images. Add your own images above whenever you're ready.")
    if c2.button("Stop using examples"):
        state.use_demo = False
        st.rerun()
elif not uploads and demo_files:
    if st.button("No images at hand? Try it with example images"):
        state.use_demo = True
        st.rerun()

sidecars = {Path(f.name).stem: f.getvalue().decode(errors="ignore")
            for f in (uploads or []) if f.name.lower().endswith(".txt")}
sources = [(f.name, f.getvalue()) for f in (uploads or []) if not f.name.lower().endswith(".txt")]
if state.use_demo:
    sources += [(p.name, p.read_bytes()) for p in demo_files]

if not sources:
    st.markdown(
        "**What you will get:** for every diatom in each image, its size in µm, shape, which way it "
        "lies, and whether it is intact, cracked or broken, plus the position and size of every pore. "
        "Everything downloads as one Excel spreadsheet.")
    st.stop()


# --------------------------------------------------------------------------- step 2

st.subheader("2 · What does your sample look like?")
options = ["apart", "round", "manual"] + (["model"] if trained_models() else [])
sample = st.radio("Choose the description that fits best. You can change it at any time.", options,
                  format_func=lambda k: SAMPLE_TYPES[k][0], captions=[SAMPLE_TYPES[k][1] for k in options],
                  key="sample_type")
cell_diameter = (2.0, 8.0)
cellpose_model = ""
if sample == "round":
    cell_size = st.number_input("About how wide is one cell? (µm)", 0.5, 100.0, 4.0, 0.5,
                                help="A rough guess is fine: cells from about 60 % to 150 % of this size are found.")
    cell_diameter = (round(cell_size * 0.6, 2), round(cell_size * 1.5, 2))
elif sample == "model":
    models = trained_models()
    choice = st.selectbox("Model", models, format_func=lambda p: p.name) if len(models) > 1 else models[0]
    cellpose_model = str(choice)
    try:
        import cellpose  # noqa: F401
    except ImportError:
        st.error("The trained model needs the Cellpose add-on, which isn't installed on this computer. "
                 "Ask whoever set up the tool to install it (see README), or pick another option.")
        st.stop()

method = {"apart": "classical", "round": "round_cells", "manual": "manual", "model": "cellpose"}[sample]
settings = {
    "method": method, "cellpose_model": cellpose_model, "cell_diameter": cell_diameter,
    "cell_roundness": roundness, "min_size_um": min_size, "split": split, "pore_range": pore_range,
    "pore_sensitivity": pore_sensitivity, "frag_corner": frag_corner, "frag_solidity": frag_solidity,
}
settings_key = tuple(sorted(settings.items()))

results, failed = [], []
progress = st.progress(0.0, text="Measuring your images…")
for i, (name, data) in enumerate(sources):
    ov = state.overrides.get(name, {})
    try:
        results.append(run_analysis(data, name, settings_key, ov.get("um_per_px", global_um),
                                    ov.get("bar_um", global_bar), ov.get("databar_top"), library_dir, lib_sig,
                                    sidecars.get(Path(name).stem), tuple(state.edits.get(name, []))))
    except Exception as exc:  # show a friendly note and keep going with the other images
        failed.append((name, exc))
    progress.progress((i + 1) / len(sources), text=f"Measured {i + 1} of {len(sources)} images")
progress.empty()
for name, exc in failed:
    st.error(f"**{name}** could not be read. Is it an image file? (Details: {exc})")
if not results:
    st.stop()
config = build_config(dict(settings_key))


# --------------------------------------------------------------------------- step 3

st.subheader("3 · Check each image, and fix any mistakes")
names = [r.name for r in results]


def image_label(name):
    r = results[names.index(name)]
    mark = "⚠️ scale needed" if not r.calibration.ok else f"{len(r.frustules)} diatoms"
    return f"{name}  ({mark})"


chosen = st.selectbox("Image", names, format_func=image_label) if len(names) > 1 else names[0]
res = results[names.index(chosen)]
cal = res.calibration
um = cal.um_per_px if cal.ok else None

# Scale, in words, with a way to fix it.
sentence = scale_sentence(cal)
if sentence:
    st.success(f"**Scale:** {sentence}", icon="📏")
    if "warning" in cal.details:
        st.warning("Two scale readings for this image disagree. " + cal.details["warning"])
else:
    st.warning("**We couldn't work out the scale of this image**, so sizes can't be given in µm yet.", icon="📏")
with st.expander("Scale looks wrong? Correct it", expanded=not cal.ok):
    with st.form(f"scale_{chosen}"):
        if cal.scale_bar_length_px:
            st.markdown("The scale bar we found is marked with a **pink box** on the image. "
                        "What length is written next to it?")
            c1, c2 = st.columns([2, 1])
            bar_val = c1.number_input("The scale bar shows", min_value=0.0, value=0.0, step=0.5)
            bar_unit = c2.selectbox("Unit", list(UNITS), index=1)
            px_val, px_unit = 0.0, "nm"
        else:
            st.markdown("No scale bar was found. Enter the pixel size from the microscope's report.")
            c1, c2 = st.columns([2, 1])
            px_val = c1.number_input("1 pixel equals", min_value=0.0, value=0.0, step=0.1, format="%.4f")
            px_unit = c2.selectbox("Unit", ["nm", "µm"], index=0)
            bar_val, bar_unit = 0.0, "µm"
        a, b = st.columns(2)
        if a.form_submit_button("Use this scale", type="primary"):
            if bar_val > 0:
                state.overrides[chosen] = {"bar_um": bar_val * UNITS[bar_unit]}
            elif px_val > 0:
                state.overrides[chosen] = {"um_per_px": px_val * UNITS[px_unit]}
            st.rerun()
        if b.form_submit_button("Go back to automatic"):
            state.overrides.pop(chosen, None)
            st.rerun()

counts = {k: sum(f.damage == k for f in res.frustules) for k in CONDITION}
m = st.columns(5)
m[0].metric("Diatoms found", len(res.frustules))
m[1].metric("Intact", counts["intact"])
m[2].metric("Cracked", counts["cracked"])
m[3].metric("Broken", counts["fragmented"])
m[4].metric("Pores measured", sum(len(f.pores) for f in res.frustules))
if counts["uncertain"] or counts["not graded"]:
    st.caption(f"{counts['uncertain']} diatom(s) are cut off by the image edge and {counts['not graded']} were "
               "not assessed for damage, so they are not counted as intact, cracked or broken.")

left, right = st.columns([3, 2])
with left:
    tool = st.segmented_control("What do you want to do?", ["👀 Look", "➕ Add a missed diatom", "➖ Remove a wrong one"],
                                default="👀 Look", key=f"tool_{chosen}") or "👀 Look"
    size_hint_um = 10.0
    if tool.startswith("➕"):
        e1, e2 = st.columns([3, 2])
        e1.info("**Drag along the diatom from one tip to the other.** The outline is traced for you. "
                "For a round diatom you can also just click its centre.")
        default_size = float(np.median([f.equiv_diameter_px for f in res.frustules]) * um) \
            if (res.frustules and um) else 10.0
        size_hint_um = e2.number_input("Round diatoms are about (µm) wide", 0.1, 5000.0, round(default_size, 1), 0.5,
                                       key=f"size_hint_{chosen}")
    elif tool.startswith("➖"):
        st.info("**Click on an outline** that isn't a diatom, and it will be removed.")

    show_pores = st.toggle("Show pores", value=True, key=f"pores_{chosen}")
    overlay = render_overlay(res, show_pores=show_pores, show_axes=False)
    display = Image.fromarray(overlay)
    display.thumbnail((1400, 1400))
    if tool.startswith("👀"):
        st.image(display, width="stretch")
    else:
        click = streamlit_image_coordinates(display, key=f"clicks_{chosen}", width="stretch", click_and_drag=True,
                                            image_format="JPEG", jpeg_quality=85, cursor="crosshair")
        if click and click.get("unix_time") != state.last_click.get(chosen):
            state.last_click[chosen] = click["unix_time"]
            fx = overlay.shape[1] / click["width"]
            fy = overlay.shape[0] / click["height"]
            x1, y1 = click["x1"] * fx, click["y1"] * fy
            x2, y2 = click["x2"] * fx, click["y2"] * fy
            if y1 < res.analysis_height:
                if tool.startswith("➕"):
                    size_px = size_hint_um / um if um else size_hint_um
                    edit = ("add", x1, y1, min(max(x2, 0), overlay.shape[1] - 1),
                            min(max(y2, 0), res.analysis_height - 1), size_px)
                else:
                    edit = ("remove", x1, y1, x1, y1, 0)
                state.edits.setdefault(chosen, []).append(edit)
                st.rerun()
    st.markdown(legend_html(), unsafe_allow_html=True)

    edits_here = state.edits.get(chosen, [])
    if edits_here:
        c1, c2, c3 = st.columns([2, 1, 1])
        added = sum(e[0] == "add" for e in edits_here)
        c1.caption(f"Your changes to this image: {added} added, {len(edits_here) - added} removed")
        if c2.button("↶ Undo", key=f"undo_{chosen}"):
            edits_here.pop()
            st.rerun()
        if c3.button("Start over", key=f"clear_{chosen}"):
            state.edits[chosen] = []
            st.rerun()

with right:
    table = friendly_table(res)
    if len(table):
        st.markdown("**The diatoms in this image** (numbers match the image)")
        st.dataframe(table, hide_index=True, width="stretch", height=520,
                     column_config={c: st.column_config.NumberColumn(format="%.2f") for c in table.columns
                                    if table[c].dtype.kind == "f"})
    elif sample == "manual":
        st.info("Nothing is marked yet. Choose **➕ Add a missed diatom** and drag along each diatom.")
    else:
        st.info("No diatoms were found in this image. Try another description in step 2, or mark them "
                "yourself with **➕ Add a missed diatom**.")

with st.expander("More details for this image (every measurement, pores, size charts)"):
    tab_f, tab_p, tab_d = st.tabs(["All measurements", "Pores", "Size charts"])
    with tab_f:
        st.dataframe(pd.DataFrame(frustule_rows(res)), hide_index=True, width="stretch")
    with tab_p:
        pores_df = pd.DataFrame(pore_rows(res))
        st.caption("Positions are measured from the top-left corner of the image.")
        st.dataframe(pores_df, hide_index=True, width="stretch", height=380)
    with tab_d:
        if um is None:
            st.info("Charts appear once the scale is known.")
        else:
            c1, c2 = st.columns(2)
            rows_all = pd.DataFrame([r for x in results for r in frustule_rows(x)])
            with c1:
                st.markdown("**Diatom length, all images**")
                if len(rows_all) and rows_all["length_um"].notna().any():
                    st.altair_chart(histogram(rows_all["length_um"].dropna(), "Length (µm)"), width="stretch")
            with c2:
                st.markdown("**Pore size, this image**")
                if len(pores_df):
                    st.altair_chart(histogram(pores_df["diameter_um"].dropna(), "Pore diameter (µm)"),
                                    width="stretch")
                else:
                    st.info("No pores were measured in this image.")


# --------------------------------------------------------------------------- step 4

st.subheader("4 · Save your results")
all_rows = [r for x in results for r in frustule_rows(x)]
st.markdown(f"**{len(results)} image(s), {len(all_rows)} diatoms.** The spreadsheet has one sheet listing every "
            "diatom, one listing every pore, a summary per image, and a sheet explaining every column.")
missing = [r.name for r in results if not r.calibration.ok]
if missing:
    st.warning(f"{len(missing)} image(s) have no scale yet, so their sizes are in pixels only: "
               f"{', '.join(missing)}. Pick each one in step 3 to fix its scale.")
xlsx = io.BytesIO()
write_excel(results, xlsx, config)
zbuf = io.BytesIO()
with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
    for x in results:
        zf.writestr(f"{Path(x.name).stem}_marked.png", png_bytes(render_overlay(x)))
d1, d2 = st.columns(2)
d1.download_button("⬇️ Download results (Excel)", xlsx.getvalue(), "diatom_results.xlsx", type="primary",
                   width="stretch", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
d2.download_button("⬇️ Download the marked-up images (ZIP)", zbuf.getvalue(), "diatom_images_marked.zip",
                   width="stretch", mime="application/zip")


# --------------------------------------------------------------------------- more tools

st.divider()
st.subheader("More tools")

with st.expander("Teach the tool species names"):
    st.markdown("Tell the tool which species some of the diatoms are. From then on, it suggests species "
                "names for diatoms in every image. Two or three good examples per species is a fine start.")
    if not res.frustules:
        st.info("This image has no diatoms to use as examples.")
    else:
        with st.form(f"teach_{chosen}"):
            ids = st.multiselect("Which diatoms? (use the numbers on the image)",
                                 [f.frustule_id for f in res.frustules])
            existing = library.species
            pick = st.selectbox("Species", ["➕ A new species…"] + existing) if existing else "➕ A new species…"
            new_name = st.text_input("New species name", placeholder="e.g. Thalassiosira pseudonana")
            if st.form_submit_button("Save as examples", type="primary"):
                species = new_name.strip() if pick.startswith("➕") else pick
                if not ids or not species:
                    st.error("Pick at least one diatom and give the species a name.")
                else:
                    for fid in ids:
                        fr = next(f for f in res.frustules if f.frustule_id == fid)
                        library.add(species, fr, res.image, res.name, um)
                    st.success(f"Saved {len(ids)} example(s) of {species}.")
                    st.rerun()
    if len(library):
        st.markdown("**Species the tool knows**")
        for sp in library.species:
            previews = [p for s, _, p in library.exemplars if s == sp and p is not None]
            thumbs = [p.with_suffix(".png") for p in previews if p.with_suffix(".png").exists()]
            st.markdown(f"*{sp}*: {len(previews)} example(s)")
            if thumbs:
                st.image([str(t) for t in thumbs[:8]], width=90)
    st.markdown("**Add a whole reference collection** (a .zip with one folder of images per species)")
    zip_up = st.file_uploader("Reference collection (.zip)", type=["zip"], key="library_zip",
                              label_visibility="collapsed")
    if zip_up is not None and st.button("Add this collection"):
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(io.BytesIO(zip_up.getvalue())) as zf:
                zf.extractall(tmp)  # zipfile strips absolute paths and ".." components
            root = Path(tmp)
            dirs = [d for d in root.iterdir() if d.is_dir() and not d.name.startswith(("__", "."))]
            if len(dirs) == 1 and not any(f.is_file() for f in root.iterdir()):
                root = dirs[0]  # the zip holds a single parent folder
            with st.spinner("Reading the collection…"):
                added = build_library(root, "folders", library_dir, shots=10)
        if added:
            st.success("Added " + ", ".join(f"{s} ({n})" for s, n in sorted(added.items())))
            st.cache_data.clear()
            st.rerun()
        else:
            st.error("No folders of diatom images were found in that zip.")

with st.expander("Help the tool learn to find diatoms (save training examples)"):
    st.markdown("When every diatom in this image is outlined correctly (after your fixes in step 3), save it "
                "as a training example. With 10–20 such images, whoever looks after the tool can train a "
                "detection model for your samples (see README, *Training a detection model*). It then "
                "appears in step 2 as *Use the lab's trained model*.")
    if st.button("Save this image as a training example", type="primary", key=f"save_train_{chosen}"):
        stem = Path(chosen).stem.replace(" ", "_")
        save_training_example(res.image[: res.analysis_height], res.labels, train_dir, stem)
        st.success(f"Saved, with {len(res.frustules)} outlined diatoms.")
    folder = Path(train_dir)
    saved = sorted(folder.glob("*_masks.png")) if folder.exists() else []
    if saved:
        st.caption(f"{len(saved)} training example(s) saved so far.")
        zbuf2 = io.BytesIO()
        with zipfile.ZipFile(zbuf2, "w", zipfile.ZIP_DEFLATED) as zf:
            for mask in saved:
                zf.write(mask, mask.name)
                image_file = mask.with_name(mask.name.replace("_masks.png", ".png"))
                if image_file.exists():
                    zf.write(image_file, image_file.name)
        st.download_button("⬇️ Download all training examples (ZIP)", zbuf2.getvalue(),
                           "diatom_training_examples.zip", mime="application/zip")

with st.expander("How to use this tool"):
    st.markdown(
        "1. **Add images** in step 1: drag them in, several at once is fine.\n"
        "2. **Describe the sample** in step 2. If the results look poor, try another description.\n"
        "3. **Check each image** in step 3. Pick an image from the list; outlines are coloured by condition. "
        "Missed a diatom? Choose *➕ Add a missed diatom* and drag along it. Wrong outline? Choose "
        "*➖ Remove a wrong one* and click it. *↶ Undo* takes back your last change.\n"
        "4. **Download** the Excel file in step 4.\n\n"
        "The scale is read automatically from the microscope's file or the scale bar; if it can't be, "
        "you'll be asked what the scale bar says. Nothing leaves this computer. To quit, close this browser "
        "tab and the black window that opened with it.")
