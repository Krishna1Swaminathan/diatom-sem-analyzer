# Synthetic benchmark (30 frames, crowded)

Random scenes of 7 look-alike species at 35-70 nm/pixel with random damage and noise; the scale is read from the image's own scale bar.

## Detection, scale, measurements

| measure | result |
|---|---|
| Frustules (truth / detected / matched IoU≥0.5) | 156 / 125 / 117 |
| Precision / recall / F1 | 93.6 % / 75.0 % / 83.3 % |
| Mean count error per image | 1.03 |
| Scale correct (±1 %) | 30/30 |
| Length error (mean / 90th pct) | 5.3 % / 9.5 % |
| Width error (mean) | 14.5 % |
| Orientation error (mean / max) | 1.24° / 18.92° |
| Centric vs pennate correct | 91.2 % |
| Pore count error (mean) | 12.8 % |
| Pore diameter bias (mean) | +5 nm |
| Time per image | 2.0 s |

## Damage grading (no species library)

Accuracy: **84.6 %**

| truth \ predicted | intact | cracked | fragmented | uncertain |
|---|---|---|---|---|
| intact | 76 | 4 | 10 | 0 |
| cracked | 1 | 11 | 0 | 0 |
| fragmented | 3 | 0 | 12 | 0 |

| species | damage correct |
|---|---|
| Coscinodiscus-like | 14/18 |
| Cyclotella-like | 18/21 |
| Cymbella-like | 21/23 |
| Navicula-like | 10/11 |
| Pinnularia-like | 17/20 |
| Synedra-like | 5/9 |
| Triceratium-like | 14/15 |

### Species, 1 example(s) per species (all frustules)

Accuracy: **80.3 %** (94/117)

| species | correct | accuracy |
|---|---|---|
| Coscinodiscus-like | 11/18 | 61.1 % |
| Cyclotella-like | 21/21 | 100.0 % |
| Cymbella-like | 14/23 | 60.9 % |
| Navicula-like | 10/11 | 90.9 % |
| Pinnularia-like | 19/20 | 95.0 % |
| Synedra-like | 7/9 | 77.8 % |
| Triceratium-like | 12/15 | 80.0 % |

Most common mistakes: Cymbella-like → Navicula-like (9); Coscinodiscus-like → unknown (3); Triceratium-like → Pinnularia-like (3); Coscinodiscus-like → Cymbella-like (2); Synedra-like → Navicula-like (2); Coscinodiscus-like → Navicula-like (1)

Intact frustules only: 83.3 %. Damage accuracy with this library (species-relative outline tests): 84.6 %.

### Species, 3 example(s) per species (all frustules)

Accuracy: **87.2 %** (102/117)

| species | correct | accuracy |
|---|---|---|
| Coscinodiscus-like | 11/18 | 61.1 % |
| Cyclotella-like | 21/21 | 100.0 % |
| Cymbella-like | 21/23 | 91.3 % |
| Navicula-like | 9/11 | 81.8 % |
| Pinnularia-like | 19/20 | 95.0 % |
| Synedra-like | 9/9 | 100.0 % |
| Triceratium-like | 12/15 | 80.0 % |

Most common mistakes: Coscinodiscus-like → unknown (4); Triceratium-like → Pinnularia-like (3); Cymbella-like → Navicula-like (2); Navicula-like → Cymbella-like (2); Coscinodiscus-like → Navicula-like (1); Coscinodiscus-like → Cyclotella-like (1)

Intact frustules only: 88.9 %. Damage accuracy with this library (species-relative outline tests): 84.6 %.

### Species, 5 example(s) per species (all frustules)

Accuracy: **91.5 %** (107/117)

| species | correct | accuracy |
|---|---|---|
| Coscinodiscus-like | 11/18 | 61.1 % |
| Cyclotella-like | 21/21 | 100.0 % |
| Cymbella-like | 22/23 | 95.7 % |
| Navicula-like | 10/11 | 90.9 % |
| Pinnularia-like | 19/20 | 95.0 % |
| Synedra-like | 9/9 | 100.0 % |
| Triceratium-like | 15/15 | 100.0 % |

Most common mistakes: Coscinodiscus-like → unknown (5); Coscinodiscus-like → Synedra-like (1); Coscinodiscus-like → Cymbella-like (1); Cymbella-like → Navicula-like (1); Pinnularia-like → Navicula-like (1); Navicula-like → Cymbella-like (1)

Intact frustules only: 91.1 %. Damage accuracy with this library (species-relative outline tests): 84.6 %.

### Species missing from the library

Leaving each species out of a 5-example library in turn, **63.3 %** of its intact specimens were reported as *unknown* (57/90); the rest were given the closest look-alike's name.

## Per image

| seed | truth | detected | matched | scale source | scale | s |
|---|---|---|---|---|---|---|
| 0 | 6 | 4 | 3 | scale_bar | ok | 2.9 |
| 1 | 5 | 4 | 4 | scale_bar | ok | 1.4 |
| 2 | 6 | 4 | 3 | scale_bar | ok | 1.2 |
| 3 | 6 | 5 | 5 | scale_bar | ok | 4.3 |
| 4 | 4 | 4 | 4 | scale_bar | ok | 1.8 |
| 5 | 6 | 5 | 5 | scale_bar | ok | 1.6 |
| 6 | 5 | 4 | 3 | scale_bar | ok | 1.8 |
| 7 | 6 | 6 | 6 | scale_bar | ok | 3.4 |
| 8 | 6 | 3 | 2 | scale_bar | ok | 2.0 |
| 9 | 5 | 4 | 4 | scale_bar | ok | 1.0 |
| 10 | 6 | 3 | 2 | scale_bar | ok | 2.4 |
| 11 | 3 | 3 | 3 | scale_bar | ok | 1.0 |
| 12 | 5 | 4 | 4 | scale_bar | ok | 1.8 |
| 13 | 6 | 5 | 5 | scale_bar | ok | 1.9 |
| 14 | 3 | 3 | 3 | scale_bar | ok | 2.4 |
| 15 | 5 | 5 | 5 | scale_bar | ok | 1.1 |
| 16 | 5 | 4 | 4 | scale_bar | ok | 1.0 |
| 17 | 6 | 3 | 2 | scale_bar | ok | 1.3 |
| 18 | 7 | 5 | 5 | scale_bar | ok | 1.6 |
| 19 | 5 | 5 | 5 | scale_bar | ok | 1.4 |
| 20 | 6 | 5 | 5 | scale_bar | ok | 3.2 |
| 21 | 4 | 3 | 2 | scale_bar | ok | 2.4 |
| 22 | 6 | 6 | 6 | scale_bar | ok | 1.2 |
| 23 | 3 | 3 | 3 | scale_bar | ok | 2.4 |
| 24 | 4 | 3 | 3 | scale_bar | ok | 2.0 |
| 25 | 5 | 5 | 5 | scale_bar | ok | 1.9 |
| 26 | 6 | 5 | 5 | scale_bar | ok | 1.6 |
| 27 | 3 | 3 | 3 | scale_bar | ok | 2.4 |
| 28 | 6 | 4 | 4 | scale_bar | ok | 3.2 |
| 29 | 7 | 5 | 4 | scale_bar | ok | 3.4 |