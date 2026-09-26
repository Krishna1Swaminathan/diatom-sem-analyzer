"""Diatom SEM Analyzer - point-and-click interface.

Run with:  streamlit run app.py
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
from diatom_analyzer.visualize import DAMAGE_COLORS, render_overlay

HERE = Path(__file__).parent
DEMO_DIR = HERE / "sample_data"
DEFAULT_LIBRARY = HERE / "species_library"
UNITS = {"nm": 1e-3, "µm": 1.0, "mm": 1e3}
SERIES_BLUE = "#2a78d6"

st.set_page_config(page_title="Diatom SEM Analyzer", page_icon="🔬", layout="wide")

state = st.session_state
state.setdefault("overrides", {})
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


def histogram(values, label):
    df = pd.DataFrame({"value": values})
    return (
        alt.Chart(df)
        .mark_bar(color=SERIES_BLUE, cornerRadiusTopLeft=4, cornerRadiusTopRight=4, binSpacing=2)
        .encode(
            x=alt.X("value:Q", bin=alt.Bin(maxbins=30), title=label),
            y=alt.Y("count()", title="Count"),
            tooltip=[alt.Tooltip("value:Q", bin=alt.Bin(maxbins=30), title=label, format=".3g"),
                     alt.Tooltip("count()", title="Count")],
        )
        .properties(height=240)
        .configure_axis(gridOpacity=0.35, domainOpacity=0.4)
    )


def legend_html():
    chips = []
    for name, (r, g, b) in DAMAGE_COLORS.items():
        chips.append(f"<span style='display:inline-flex;align-items:center;margin-right:14px'>"
                     f"<span style='width:14px;height:14px;border-radius:3px;background:rgb({r},{g},{b});"
                     f"display:inline-block;margin-right:6px'></span>{name}</span>")
    chips.append("<span style='display:inline-flex;align-items:center'>"
                 "<span style='width:14px;height:14px;border-radius:50%;border:2px solid rgb(86,180,233);"
                 "display:inline-block;margin-right:6px'></span>pore</span>")
    return "<div style='font-size:0.9rem'>" + "".join(chips) + "</div>"


def png_bytes(rgb):
    ok, buf = cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    return buf.tobytes()


FRUSTULE_COLUMNS = {
    "frustule_id": "ID", "damage": "Damage", "morphotype": "Morphotype", "species": "Species",
    "species_confidence": "Match", "length_um": "Length (µm)", "width_um": "Width (µm)",
    "orientation_deg": "Orientation (°)", "pore_count": "Pores", "pore_median_diameter_um": "Median pore Ø (µm)",
    "pore_nn_spacing_um": "Pore spacing (µm)", "porosity": "Porosity", "view": "View",
    "equiv_diameter_um": "Equiv. diam. (µm)", "touches_image_edge": "At image edge",
}


# --------------------------------------------------------------------------- sidebar

with st.sidebar:
    st.title("🔬 Diatom SEM Analyzer")
    st.caption("Image in, measurements out. Everything runs on this computer.")

    st.subheader("1 · Images")
    uploads = st.file_uploader("SEM images (TIFF, PNG, JPG), plus any .txt metadata files",
                               type=[s.strip(".") for s in IMAGE_SUFFIXES] + ["txt"],
                               accept_multiple_files=True)
    demo_files = sorted(p for p in DEMO_DIR.glob("*") if p.suffix.lower() in IMAGE_SUFFIXES)
    if demo_files:
        state.use_demo = st.toggle("Include demo images", value=state.use_demo or not uploads,
                                   help="Synthetic SEM images with known answers, for trying the tool.")

    st.subheader("2 · Scale")
    scale_mode = st.radio("How should the scale be found?",
                          ["Automatic (metadata or scale bar)", "Scale bar length I type in", "µm per pixel I type in"],
                          help="Automatic reads the pixel size stored in the file by the microscope, or finds the "
                               "scale bar and reads its label. The pixel size is never assumed.")
    global_um, global_bar = None, None
    if scale_mode == "Scale bar length I type in":
        c1, c2 = st.columns([2, 1])
        value = c1.number_input("Scale bar shows", min_value=0.0, value=10.0, step=1.0)
        unit = c2.selectbox("Unit", list(UNITS), index=1)
        global_bar = value * UNITS[unit] if value > 0 else None
    elif scale_mode == "µm per pixel I type in":
        global_um = st.number_input("µm per pixel", min_value=0.0, value=0.0, step=0.001, format="%.5f") or None
    if not ocr_available():
        st.info("Scale-bar text reading (Tesseract OCR) isn't installed, so automatic mode uses file "
                "metadata only. You'll be asked what the scale bar shows when needed.", icon="ℹ️")

    st.subheader("3 · Species library")
    library_dir = st.text_input("Reference folder", value=str(DEFAULT_LIBRARY),
                                help="One sub-folder per species. Add exemplars from the 'Teach species' tab.")
    lib_sig = library_signature(library_dir)
    library = SpeciesLibrary(library_dir)
    if len(library):
        st.caption(f"{len(library.species)} species, {len(library)} exemplars")
    else:
        st.caption("Empty: frustules get a morphotype only. Teach species from any result.")
    with st.expander("Import labelled examples"):
        st.caption("A .zip with one folder per species, each image showing one diatom (for example a "
                   "downloaded reference collection, or your own sorted images).")
        zip_up = st.file_uploader("Zip of species folders", type=["zip"], key="library_zip")
        per_species = st.number_input("Examples per species", 1, 100, 10)
        if zip_up is not None and st.button("Import into library"):
            with tempfile.TemporaryDirectory() as tmp:
                with zipfile.ZipFile(io.BytesIO(zip_up.getvalue())) as zf:
                    zf.extractall(tmp)  # zipfile strips absolute paths and ".." components
                root = Path(tmp)
                dirs = [d for d in root.iterdir() if d.is_dir() and not d.name.startswith(("__", "."))]
                if len(dirs) == 1 and not any(f.is_file() for f in root.iterdir()):
                    root = dirs[0]  # the zip holds a single parent folder
                with st.spinner("Analysing examples…"):
                    added = build_library(root, "folders", library_dir, shots=int(per_species))
            if added:
                st.success("Imported " + ", ".join(f"{s} ({n})" for s, n in sorted(added.items())))
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("No species folders with detectable diatoms were found in that zip.")

    with st.expander("Advanced settings"):
        methods = {"Separate frustules (general)": "classical",
                   "Round centric cells, crowded (e.g. Thalassiosira)": "round_cells",
                   "Manual only (outline frustules by hand)": "manual"}
        try:
            import cellpose  # noqa: F401
            methods["Cellpose (deep learning)"] = "cellpose"
        except ImportError:
            pass
        method_label = st.selectbox(
            "Detection mode", list(methods),
            help="General: frustules standing apart on a smoother background. Round centric cells: finds "
                 "the bright rims of round valves in crowded cultures or on textured substrates; damage "
                 "is not graded in this mode. Manual only: start with nothing detected and outline each "
                 "frustule by dragging along it (for images the automatic modes cannot handle).")
        round_mode = methods[method_label] == "round_cells"
        cellpose_model = ""
        if methods[method_label] == "cellpose":
            trained = sorted(str(p) for p in (HERE / "models").glob("*") if p.is_file() and p.suffix == "")
            choice = st.selectbox("Cellpose model", trained + ["cyto3 (built-in, general cells)"],
                                  help="Models you trained with `python -m diatom_analyzer.train` appear here.")
            cellpose_model = "cyto3" if choice.startswith("cyto3") else choice
        settings = {
            "method": methods[method_label],
            "cellpose_model": cellpose_model,
            "cell_diameter": st.slider("Cell diameter range (µm)", 0.5, 60.0, (2.0, 8.0), 0.5,
                                       disabled=not round_mode),
            "cell_roundness": st.slider("Rim completeness required", 0.3, 0.95, 0.5, 0.05,
                                        disabled=not round_mode,
                                        help="Lower finds partly hidden or tilted cells, but may add false "
                                             "circles; higher keeps only clear, round rims."),
            "min_size_um": st.number_input("Ignore objects smaller than (µm)", 0.1, 500.0, 3.0, 0.5),
            "split": st.checkbox("Separate touching frustules", value=True),
            "pore_range": st.slider("Pore diameter range (µm)", 0.01, 10.0, (0.03, 4.0), 0.01),
            "pore_sensitivity": st.slider("Pore detection strictness", 0.2, 1.5, 0.5, 0.05,
                                          help="Lower finds fainter pores; higher only keeps high-contrast ones."),
            "frag_corner": st.slider("Fragment if the outline has an inward corner sharper than (°)", 20, 90, 40, 1,
                                     help="Broken edges meet the natural margin at sharp inward corners; "
                                          "intact outlines, even crescent-shaped ones, curve smoothly."),
            "frag_solidity": st.slider("Fragment if solidity below", 0.5, 0.95, 0.85, 0.01,
                                       help="Solidity = area / convex-hull area."),
        }
    st.caption(f"v{__version__} · open source")


# --------------------------------------------------------------------------- inputs

# Hitachi and JEOL write calibration to a .txt with the same name as the image.
sidecars = {Path(f.name).stem: f.getvalue().decode(errors="ignore")
            for f in (uploads or []) if f.name.lower().endswith(".txt")}
sources = [(f.name, f.getvalue()) for f in (uploads or []) if not f.name.lower().endswith(".txt")]
if state.use_demo:
    sources += [(p.name, p.read_bytes()) for p in demo_files]

if not sources:
    st.header("Measure diatoms in SEM images")
    st.markdown(
        "1. **Add images** in the sidebar (or switch on the demo images).\n"
        "2. The scale is read from the file or the scale bar automatically; you can override it.\n"
        "3. Review the annotated image, then **download the spreadsheet**.\n\n"
        "For every frustule you get the count, morphotype (and species once you teach some), size in µm, "
        "orientation, valve/girdle view and damage grade, plus every pore's position and diameter.")
    st.stop()

settings_key = tuple(sorted(settings.items()))
results = []
progress = st.progress(0.0, text="Analysing…")
for i, (name, data) in enumerate(sources):
    ov = state.overrides.get(name, {})
    try:
        res = run_analysis(data, name, settings_key, ov.get("um_per_px", global_um), ov.get("bar_um", global_bar),
                           ov.get("databar_top"), library_dir, lib_sig,
                           sidecars.get(Path(name).stem), tuple(state.edits.get(name, [])))
        results.append(res)
    except Exception as exc:
        st.error(f"Could not analyse {name}: {exc}")
    progress.progress((i + 1) / len(sources), text=f"Analysed {name}")
progress.empty()
if not results:
    st.stop()

config = build_config(dict(settings_key))

# --------------------------------------------------------------------------- batch overview

st.header("Results")
all_frustules = pd.DataFrame([r for res in results for r in frustule_rows(res)])
all_pores = pd.DataFrame([r for res in results for r in pore_rows(res)])

cols = st.columns(5)
cols[0].metric("Images", len(results))
cols[1].metric("Frustules", len(all_frustules))
for col, grade in zip(cols[2:], ["intact", "cracked", "fragmented"]):
    col.metric(grade.capitalize(), int((all_frustules["damage"] == grade).sum()) if len(all_frustules) else 0)

xlsx = io.BytesIO()
write_excel(results, xlsx, config)
zbuf = io.BytesIO()
with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
    for res in results:
        zf.writestr(f"{Path(res.name).stem}_annotated.png", png_bytes(render_overlay(res)))
d1, d2, d3 = st.columns(3)
d1.download_button("⬇️ Spreadsheet (.xlsx)", xlsx.getvalue(), "diatom_results.xlsx", type="primary",
                   width="stretch",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
d2.download_button("⬇️ Pore table (.csv)", all_pores.to_csv(index=False).encode(), "diatom_pores.csv",
                   width="stretch", mime="text/csv")
d3.download_button("⬇️ Annotated images (.zip)", zbuf.getvalue(), "diatom_annotated.zip",
                   width="stretch", mime="application/zip")

no_scale = [r.name for r in results if not r.calibration.ok]
if no_scale:
    st.warning(f"No physical scale yet for: {', '.join(no_scale)}. Open the image below and enter what its "
               "scale bar shows.", icon="📏")

# --------------------------------------------------------------------------- one image

st.divider()
names = [r.name for r in results]
chosen = st.selectbox("Inspect image", names)
res = results[names.index(chosen)]
cal = res.calibration
um = cal.um_per_px if cal.ok else None

m = st.columns(6)
m[0].metric("Frustules", len(res.frustules))
for col, grade in zip(m[1:4], ["intact", "cracked", "fragmented"]):
    col.metric(grade.capitalize(), sum(f.damage == grade for f in res.frustules))
m[4].metric("Pores", sum(len(f.pores) for f in res.frustules))
m[5].metric("Scale", f"{um * 1000:.3g} nm/px" if um else "missing", help=f"Source: {cal.source}")
for w in res.warnings:
    st.warning(w)

if not cal.ok:
    with st.form(f"fix_scale_{chosen}"):
        if cal.scale_bar_length_px:
            st.markdown(f"**A scale bar {cal.scale_bar_length_px:.0f} px long was found** (pink box). "
                        "What length does its label show?")
        else:
            st.markdown("**No scale bar was found.** Enter the pixel size from the microscope report.")
        c1, c2 = st.columns([2, 1])
        val = c1.number_input("Length" if cal.scale_bar_length_px else "µm per pixel", min_value=0.0,
                              value=0.0, step=0.1, format="%.4f")
        unit = c2.selectbox("Unit", list(UNITS), index=1) if cal.scale_bar_length_px else "µm"
        if st.form_submit_button("Apply scale", type="primary") and val > 0:
            key = "bar_um" if cal.scale_bar_length_px else "um_per_px"
            state.overrides[chosen] = {**state.overrides.get(chosen, {}), key: val * UNITS[unit]}
            st.rerun()

left, right = st.columns([3, 2])
with left:
    t1, t2 = st.columns(2)
    show_pores = t1.checkbox("Show pores", value=True)
    show_axes = t2.checkbox("Show long axes", value=True)
    edit_mode = st.radio("Using the mouse on the image", ["Just look", "Add a missed frustule", "Remove a detection"],
                         horizontal=True, key=f"edit_mode_{chosen}")
    size_hint_um = 10.0
    if edit_mode == "Add a missed frustule":
        e1, e2 = st.columns([3, 2])
        e1.caption("**Drag along the frustule from tip to tip.** For a round one you can also just click its "
                   "centre; the size on the right is then used as a guide.")
        default_size = float(np.median([f.equiv_diameter_px for f in res.frustules]) * um) \
            if (res.frustules and um) else 10.0
        size_hint_um = e2.number_input("Round object size (µm)", 0.1, 5000.0, round(default_size, 1), 0.5,
                                       key=f"size_hint_{chosen}")
    elif edit_mode == "Remove a detection":
        st.caption("**Click a detected frustule** to remove it.")

    overlay = render_overlay(res, show_pores=show_pores, show_axes=show_axes)
    display = Image.fromarray(overlay)
    display.thumbnail((1400, 1400))
    if edit_mode == "Just look":
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
                if edit_mode == "Add a missed frustule":
                    size_px = size_hint_um / um if um else size_hint_um
                    edit = ("add", x1, y1, min(max(x2, 0), overlay.shape[1] - 1),
                            min(max(y2, 0), res.analysis_height - 1), size_px)
                else:
                    edit = ("remove", x1, y1, x1, y1, 0)
                state.edits.setdefault(chosen, []).append(edit)
                st.rerun()
    edits_here = state.edits.get(chosen, [])
    if edits_here:
        c1, c2, c3 = st.columns([2, 1, 1])
        added = sum(e[0] == "add" for e in edits_here)
        c1.caption(f"Manual corrections: {added} added, {len(edits_here) - added} removed")
        if c2.button("Undo last", key=f"undo_{chosen}"):
            edits_here.pop()
            st.rerun()
        if c3.button("Clear all", key=f"clear_{chosen}"):
            state.edits[chosen] = []
            st.rerun()
    st.markdown(legend_html(), unsafe_allow_html=True)
    st.download_button("⬇️ This annotated image", png_bytes(overlay), f"{Path(chosen).stem}_annotated.png",
                       mime="image/png")
with right:
    rows = pd.DataFrame(frustule_rows(res))
    if len(rows):
        shown = [c for c in FRUSTULE_COLUMNS if c in rows and rows[c].notna().any() and (rows[c] != "").any()]
        view = rows[shown].rename(columns=FRUSTULE_COLUMNS)
        st.dataframe(view, hide_index=True, width="stretch", height=460,
                     column_config={c: st.column_config.NumberColumn(format="%.2f") for c in view.columns
                                    if view[c].dtype.kind == "f"})
    else:
        st.info("No frustules detected. Try lowering 'Ignore objects smaller than' in Advanced settings.")

tab_f, tab_p, tab_d, tab_c, tab_t, tab_l = st.tabs(["All frustule data", "Pores", "Distributions",
                                                    "Scale calibration", "Teach species", "Training labels"])

with tab_f:
    st.dataframe(pd.DataFrame(frustule_rows(res)), hide_index=True, width="stretch")

with tab_p:
    pores_df = pd.DataFrame(pore_rows(res))
    st.caption("Coordinates are from the image's top-left corner; 'along/across' are relative to the frustule "
               "centre and its long axis.")
    st.dataframe(pores_df, hide_index=True, width="stretch", height=420)
    st.download_button("⬇️ Pores of this image (.csv)", pores_df.to_csv(index=False).encode(),
                       f"{Path(chosen).stem}_pores.csv", mime="text/csv")

with tab_d:
    if um is None:
        st.info("Distributions are shown in µm once the scale is known.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Frustule length, all images**")
            if len(all_frustules) and all_frustules["length_um"].notna().any():
                st.altair_chart(histogram(all_frustules["length_um"].dropna(), "Length (µm)"),
                                width="stretch")
        with c2:
            st.markdown(f"**Pore diameter, {chosen}**")
            if len(pores_df):
                st.altair_chart(histogram(pores_df["diameter_um"].dropna(), "Pore diameter (µm)"),
                                width="stretch")
            else:
                st.info("No pores detected in this image.")

with tab_c:
    st.markdown(f"**Source:** {cal.source}  \n**µm per pixel:** {um if um else '—'}")
    if cal.label_text:
        st.markdown(f"**Scale-bar label read:** `{cal.label_text}`")
    if cal.scale_bar_length_px:
        st.markdown(f"**Scale bar length:** {cal.scale_bar_length_px:.0f} px")
        x0, y0, x1, y1 = cal.scale_bar_bbox
        pad = max(40, (x1 - x0) // 3)
        crop = overlay[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad]
        st.image(crop, caption="Detected scale bar")
    if "warning" in cal.details:
        st.warning(cal.details["warning"])
    st.caption("Anything wrong? Override the scale for this image:")
    with st.form(f"override_{chosen}"):
        c1, c2, c3 = st.columns([2, 1, 2])
        bar_val = c1.number_input("Scale bar shows", min_value=0.0, value=0.0, step=0.5)
        bar_unit = c2.selectbox("Unit ", list(UNITS), index=1)
        top = c3.number_input("Info strip starts at row (0 = auto)", min_value=0, value=0,
                              max_value=int(res.image.shape[0]))
        a, b = st.columns(2)
        if a.form_submit_button("Apply"):
            ov = dict(state.overrides.get(chosen, {}))
            if bar_val > 0:
                ov["bar_um"] = bar_val * UNITS[bar_unit]
            if top > 0:
                ov["databar_top"] = int(top)
            state.overrides[chosen] = ov
            st.rerun()
        if b.form_submit_button("Reset to automatic"):
            state.overrides.pop(chosen, None)
            st.rerun()

with tab_t:
    st.markdown("Tell the tool what species some frustules are. Future images are then compared with these "
                "examples; no training step is needed. Two or three good examples per species is a fine start.")
    if not res.frustules:
        st.info("No frustules in this image.")
    else:
        with st.form(f"teach_{chosen}"):
            ids = st.multiselect("Frustule IDs (numbers on the image)", [f.frustule_id for f in res.frustules])
            existing = library.species
            pick = st.selectbox("Species", ["➕ New species…"] + existing) if existing else "➕ New species…"
            new_name = st.text_input("New species name", placeholder="e.g. Aulacoseira granulata")
            if st.form_submit_button("Add to library", type="primary"):
                species = new_name.strip() if pick == "➕ New species…" else pick
                if not ids or not species:
                    st.error("Choose at least one frustule and a species name.")
                else:
                    for fid in ids:
                        fr = next(f for f in res.frustules if f.frustule_id == fid)
                        library.add(species, fr, res.image, res.name, um)
                    st.success(f"Added {len(ids)} example(s) of {species}.")
                    st.rerun()
    if len(library):
        st.markdown("**Library**")
        for sp in library.species:
            previews = [p for s, _, p in library.exemplars if s == sp]
            thumbs = [p.with_suffix(".png") for p in previews if p.with_suffix(".png").exists()]
            st.markdown(f"*{sp}* · {len(previews)} example(s)")
            if thumbs:
                st.image([str(t) for t in thumbs[:8]], width=90)

with tab_l:
    st.markdown("Once the outlines on this image are right (after any corrections), save them as a training "
                "example. A folder of these is what a segmentation model such as Cellpose learns from; see "
                "the README section *Training a detection model*.")
    t1, t2 = st.columns([3, 2])
    train_dir = t1.text_input("Training folder", value=str(HERE / "training_data"), key="train_dir")
    if t2.button("Save outlines as a training example", key=f"save_train_{chosen}", type="primary"):
        stem = Path(chosen).stem.replace(" ", "_")
        img_path, mask_path = save_training_example(res.image[: res.analysis_height], res.labels, train_dir, stem)
        st.success(f"Saved {img_path.name} and {mask_path.name} ({len(res.frustules)} outlines) to {train_dir}")
    folder = Path(train_dir)
    saved = sorted(folder.glob("*_masks.png")) if folder.exists() else []
    if saved:
        st.caption(f"{len(saved)} training example(s) in this folder.")
        zbuf2 = io.BytesIO()
        with zipfile.ZipFile(zbuf2, "w", zipfile.ZIP_DEFLATED) as zf:
            for mask in saved:
                zf.write(mask, mask.name)
                image_file = mask.with_name(mask.name.replace("_masks.png", ".png"))
                if image_file.exists():
                    zf.write(image_file, image_file.name)
        st.download_button("⬇️ All training examples (.zip)", zbuf2.getvalue(), "diatom_training_data.zip",
                           mime="application/zip")
