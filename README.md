# Diatom SEM Analyzer

**Image in, measurements out.** A laptop-friendly, fully open-source tool that takes scanning
electron microscope (SEM) images of diatoms and, for every frustule in the frame, reports:

| The lab asked for | What you get |
|---|---|
| Detect and count every frustule | Outlined and numbered on an annotated image; touching frustules are separated |
| Classify species or morphotype | Morphotype out of the box (centric, pennate, girdle view, fragment); species once you teach it a few examples |
| Size in µm | Length, width, equivalent diameter and area, in µm |
| Orientation | Long-axis angle (0-180°) **and** view: valve (face-on) or girdle (side-on) |
| Damage grade | intact / cracked / fragmented (and "uncertain" when cut off by the image edge) |
| Pore spreadsheet | Every pore's coordinates and diameter in µm, plus porosity, pore density and spacing per frustule |
| Scale from metadata or the scale bar | Read from microscope metadata, or found and read off the scale bar. **The pixel size is never hard-coded** |

Everything runs locally: no cloud, no GPU, no training step, no programming.

---

## Quick start (about 10 minutes, once)

1. **Install Python 3.10 or newer** from [python.org](https://www.python.org/downloads/). On Windows,
   tick *"Add Python to PATH"* during installation.
2. **Download this project** (green *Code* button → *Download ZIP*) and unzip it.
3. Open a terminal (Windows: *Command Prompt*; Mac: *Terminal*) in the project folder and run:
   ```
   pip install -r requirements.txt
   ```
4. *(Recommended)* Install **Tesseract OCR** so scale-bar labels can be read automatically:
   - Windows: the installer from [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki), then `pip install pytesseract`
   - Mac: `brew install tesseract && pip install pytesseract`
   - Linux: `sudo apt install tesseract-ocr && pip install pytesseract`

   Without it, scales are still read from file metadata; for images that only have a burned-in scale
   bar, the app finds the bar and asks you to type what it says ("10 µm").
5. **Start the app:**
   ```
   streamlit run app.py
   ```
   Your browser opens the analyzer. Switch on *Include demo images* to try it right away.

## Using the app

1. **Add images** in the sidebar (TIFF, PNG, JPG, BMP; 8- or 16-bit; several at once).
2. **Check the scale.** The *Scale* number above each image says where it came from
   (`metadata:FEI/Thermo`, `scale_bar`, `manual`...). If none could be found, the app shows the scale
   bar it detected and asks what length it represents.
3. **Review** the annotated image. Outlines are coloured by damage (green intact, amber cracked,
   red fragmented, grey uncertain), pores are circled in blue, and white lines show long axes.
4. **Download** the spreadsheet (all images in one workbook), a pore CSV, or the annotated images.
5. *(Optional)* **Teach species.** In the *Teach species* tab, pick a few frustule numbers, type the
   species name and click *Add to library*. From then on, every image is compared with those examples.
   Two or three good examples per species is enough to start; add more when it gets one wrong.

Thresholds (minimum object size, pore size range, damage sensitivity) are under *Advanced settings*.
Every value used is recorded in the spreadsheet's *Settings* sheet, so results are reproducible.

### Batch mode (command line)

```
python -m diatom_analyzer path/to/images/ -o results.xlsx --overlays annotated/
```
Useful options: `--bar-um 10` (the scale bar in every image is 10 µm), `--um-per-px 0.0123`,
`--library species_library`, `--min-size-um 5`, `--no-ocr`. Run with `--help` for the full list.

## The spreadsheet

| Sheet | One row per | Key columns |
|---|---|---|
| Summary | image | frustule count, damage breakdown, morphotypes, species, µm/px and its source, warnings |
| Frustules | frustule | species, morphotype, view, damage, length/width/diameter/area (µm), orientation, pore count, porosity, pore density and spacing, shape metrics |
| Pores | pore | x/y (µm from the top-left corner), along/across (µm, in the frustule's own axis frame), diameter, area, major/minor axis |
| Settings | setting | software version, run time, every threshold |
| Column guide | column | plain-language definition of every column |

## How it works

```
image ─► scale ─► find frustules ─► measure ─► pores & cracks ─► species match ─► damage ─► spreadsheet
```

**1. Scale** (`calibration.py`), in priority order:
1. A value you type in (per image or for all images).
2. Microscope metadata: FEI/Thermo Fisher and Zeiss TIFF tags, ImageJ calibration, and the `.txt`
   sidecar files written by JEOL and Hitachi instruments. Screen-DPI tags (72/300 dpi) are ignored.
3. The burned-in scale bar: the longest isolated, solid horizontal bar is measured in pixels and its
   label ("10 µm", "500 nm") is read by OCR. Implausible readings are rejected, and unusual values
   (e.g. "9 µm") are flagged for checking.
4. The *HFW* (horizontal field width) text printed on FEI/Thermo information bars.

When both metadata and a readable scale bar exist, they are cross-checked. A disagreement usually means
the image was resized after acquisition, and it is flagged in the results. The instrument information
strip at the bottom of the image is detected and excluded from analysis.

**2. Frustules** (`segmentation.py`): smoothing, removal of uneven illumination/charging with a
background-surface fit, automatic (Otsu) thresholding, closing of pore-sized gaps at the margin, hole
filling, and a conservative watershed split that separates touching frustules without cutting long
pennates in two. An optional [Cellpose](https://github.com/MouseLand/cellpose) deep-learning backend
can be switched on after `pip install cellpose`.

**3. Measurements** (`measurements.py`): length and width from the tightest rotated bounding box,
orientation from image moments, and shape descriptors (solidity, ellipse fit, rectangle fill, notch
depth). **View**: girdle views have rectangular outlines (rectangle fill ≈ 1) and valve views are
elliptical (≈ 0.79). **Morphotype**: centric (round), pennate elliptic, pennate linear (aspect ≥ 4),
girdle view, or fragment.

**4. Pores** (`pores.py`): the local shell brightness is estimated with a 70th-percentile filter, which
tolerates the bright edge effect at the rim and high porosity. Pores are dark depressions found by
hysteresis thresholding, and each pore's outline is taken at **half its own depth** (the
full-width-at-half-maximum convention), so diameters don't depend on a global threshold. Long, thin
dark features are kept separately as crack candidates.

**5. Damage** (`damage.py`): *fragmented* if the outline is far from any regular shape (low solidity,
poor fit to both an ellipse and a rectangle, or a deep bite out of the margin); *cracked* if a long
crack line crosses the shell or the outline has a notch; otherwise *intact*. When a frustule confidently
matches a species in your library, the outline tests are made **relative to that species' own typical
shape**, so naturally irregular species aren't mistaken for fragments.

**6. Species** (`classification.py`): few-shot matching against your reference library, using
rotation-invariant descriptors: outline (Fourier descriptors, aspect, solidity), size, pore pattern
(diameter, density, nearest-neighbour spacing, porosity) and surface texture (local binary patterns).
Each feature is scaled by a typical within-species variation, and a match that is too far from every
species is reported as *unknown*. Fragments are matched on pore pattern and texture only.

## Accuracy on images with known answers

The repository includes a generator of synthetic SEM frames with exact ground truth
(`diatom_analyzer/synthetic.py`): centric, pennate and girdle-view frustules with pore lattices, a
crack, a fragment, a touching pair, noise, uneven illumination and a databar with a scale bar.
Over 10 frames (70 frustules) at 25 and 50 nm/pixel, with the scale read automatically from the bar:

| Measure | Result |
|---|---|
| Frustules counted | 70 / 70 |
| Damage grade correct | 70 / 70 |
| Scale (from scale-bar OCR) | exact |
| Length | mean error 1.3 %, worst 2.5 % |
| Orientation | mean error 0.2°, worst 0.7° |
| Pore count | mean error 0.3 %, worst 2.6 % |
| Pore diameter | reads 9-33 nm large (about half a pixel of optical blur) |

Run `pytest` to reproduce the 38 automated checks, which also cover metadata formats, resized images,
16-bit TIFFs, JPEGs, dark-on-bright images, edge-cut frustules and species matching.

## Limitations and next steps

- **Validate on the lab's own images.** Synthetic images prove the maths, not the realism. The first
  step with real data is to hand-measure a few images and compare them with the spreadsheet. Every
  threshold is adjustable in *Advanced settings*.
- **Damage and view are rule-based.** Crescent-shaped or strongly asymmetric species (e.g. *Cymbella*,
  *Eunotia*) may be graded *fragmented* until they are added to the species library.
- **Dense piles** of overlapping frustules (typical of raw diatomite powder) are harder to separate
  with classical segmentation; the Cellpose backend is the upgrade path.
- **OCR on very small images** (under about 500 px wide) can misread labels. Readings are sanity-checked,
  and you can always type the value in.
- Public diatom image datasets (e.g. the [Kaggle Diatom Dataset](https://www.kaggle.com/datasets/huseyingunduz/diatom-dataset),
  [ADIAC](https://websites.rbge.org.uk/ADIAC/index.html)) are light-microscopy images. They are useful
  for testing detection and outlines, but they cannot resolve pores. SEM reference images from the lab
  are the best source for the species library.

## Project layout

```
app.py                       point-and-click interface (Streamlit)
diatom_analyzer/
  calibration.py             scale from metadata, scale bar + OCR, HFW
  segmentation.py            frustule detection and splitting
  measurements.py            size, orientation, shape, view, morphotype
  pores.py                   pore detection and crack candidates
  damage.py                  intact / cracked / fragmented rules
  classification.py          species library and few-shot matching
  pipeline.py                runs the stages for one image
  export.py                  Excel workbook
  visualize.py               annotated overlay
  synthetic.py               synthetic SEM images with ground truth
  __main__.py                batch command line
sample_data/                 demo images and their ground truth
tests/                       pytest suite
```

All dependencies are open source: NumPy, SciPy, scikit-image, OpenCV, tifffile, Pillow, pandas,
openpyxl, Streamlit and (optionally) Tesseract and Cellpose.
