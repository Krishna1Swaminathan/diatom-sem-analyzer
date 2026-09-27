# Synthetic benchmark (30 frames)

Random scenes of 7 look-alike species at 35-70 nm/pixel with random damage and noise; the scale is read from the image's own scale bar.

## Detection, scale, measurements

| measure | result |
|---|---|
| Frustules (truth / detected / matched IoU≥0.5) | 143 / 143 / 143 |
| Precision / recall / F1 | 100.0 % / 100.0 % / 100.0 % |
| Mean count error per image | 0.00 |
| Scale correct (±1 %) | 30/30 |
| Length error (mean / 90th pct) | 0.8 % / 1.5 % |
| Width error (mean) | 1.6 % |
| Orientation error (mean / max) | 0.02° / 0.18° |
| Centric vs pennate correct | 100.0 % |
| Pore count error (mean) | 1.1 % |
| Pore diameter bias (mean) | +16 nm |
| Time per image | 1.6 s |

## Damage grading (no species library)

Accuracy: **97.2 %**

| truth \ predicted | intact | cracked | fragmented | uncertain |
|---|---|---|---|---|
| intact | 103 | 0 | 0 | 0 |
| cracked | 1 | 17 | 0 | 0 |
| fragmented | 3 | 0 | 19 | 0 |

| species | damage correct |
|---|---|
| Coscinodiscus-like | 18/18 |
| Cyclotella-like | 28/28 |
| Cymbella-like | 28/29 |
| Navicula-like | 16/17 |
| Pinnularia-like | 20/20 |
| Synedra-like | 8/10 |
| Triceratium-like | 21/21 |

### Species, 1 example(s) per species (all frustules)

Accuracy: **89.5 %** (128/143)

| species | correct | accuracy |
|---|---|---|
| Coscinodiscus-like | 18/18 | 100.0 % |
| Cyclotella-like | 27/28 | 96.4 % |
| Cymbella-like | 18/29 | 62.1 % |
| Navicula-like | 17/17 | 100.0 % |
| Pinnularia-like | 20/20 | 100.0 % |
| Synedra-like | 10/10 | 100.0 % |
| Triceratium-like | 18/21 | 85.7 % |

Most common mistakes: Cymbella-like → Navicula-like (11); Triceratium-like → Pinnularia-like (3); Cyclotella-like → Cymbella-like (1)

Intact frustules only: 93.2 %. Damage accuracy with this library (species-relative outline tests): 97.2 %.

### Species, 3 example(s) per species (all frustules)

Accuracy: **94.4 %** (135/143)

| species | correct | accuracy |
|---|---|---|
| Coscinodiscus-like | 18/18 | 100.0 % |
| Cyclotella-like | 28/28 | 100.0 % |
| Cymbella-like | 26/29 | 89.7 % |
| Navicula-like | 15/17 | 88.2 % |
| Pinnularia-like | 20/20 | 100.0 % |
| Synedra-like | 10/10 | 100.0 % |
| Triceratium-like | 18/21 | 85.7 % |

Most common mistakes: Triceratium-like → Pinnularia-like (3); Cymbella-like → Navicula-like (3); Navicula-like → Cymbella-like (2)

Intact frustules only: 98.1 %. Damage accuracy with this library (species-relative outline tests): 97.2 %.

### Species, 5 example(s) per species (all frustules)

Accuracy: **98.6 %** (141/143)

| species | correct | accuracy |
|---|---|---|
| Coscinodiscus-like | 18/18 | 100.0 % |
| Cyclotella-like | 28/28 | 100.0 % |
| Cymbella-like | 28/29 | 96.6 % |
| Navicula-like | 16/17 | 94.1 % |
| Pinnularia-like | 20/20 | 100.0 % |
| Synedra-like | 10/10 | 100.0 % |
| Triceratium-like | 21/21 | 100.0 % |

Most common mistakes: Cymbella-like → Navicula-like (1); Navicula-like → Cymbella-like (1)

Intact frustules only: 100.0 %. Damage accuracy with this library (species-relative outline tests): 97.2 %.

### Species missing from the library

Leaving each species out of a 5-example library in turn, **68.9 %** of its intact specimens were reported as *unknown* (71/103); the rest were given the closest look-alike's name.

## Per image

| seed | truth | detected | matched | scale source | scale | s |
|---|---|---|---|---|---|---|
| 0 | 5 | 5 | 5 | scale_bar | ok | 2.5 |
| 1 | 5 | 5 | 5 | scale_bar | ok | 1.4 |
| 2 | 6 | 6 | 6 | scale_bar | ok | 1.1 |
| 3 | 4 | 4 | 4 | scale_bar | ok | 2.4 |
| 4 | 3 | 3 | 3 | scale_bar | ok | 1.1 |
| 5 | 6 | 6 | 6 | scale_bar | ok | 1.4 |
| 6 | 5 | 5 | 5 | scale_bar | ok | 1.7 |
| 7 | 5 | 5 | 5 | scale_bar | ok | 2.3 |
| 8 | 5 | 5 | 5 | scale_bar | ok | 1.4 |
| 9 | 4 | 4 | 4 | scale_bar | ok | 0.9 |
| 10 | 5 | 5 | 5 | scale_bar | ok | 1.5 |
| 11 | 3 | 3 | 3 | scale_bar | ok | 0.7 |
| 12 | 5 | 5 | 5 | scale_bar | ok | 1.5 |
| 13 | 5 | 5 | 5 | scale_bar | ok | 1.4 |
| 14 | 3 | 3 | 3 | scale_bar | ok | 2.4 |
| 15 | 5 | 5 | 5 | scale_bar | ok | 0.9 |
| 16 | 4 | 4 | 4 | scale_bar | ok | 0.8 |
| 17 | 6 | 6 | 6 | scale_bar | ok | 1.0 |
| 18 | 6 | 6 | 6 | scale_bar | ok | 1.2 |
| 19 | 5 | 5 | 5 | scale_bar | ok | 1.4 |
| 20 | 5 | 5 | 5 | scale_bar | ok | 2.2 |
| 21 | 4 | 4 | 4 | scale_bar | ok | 1.8 |
| 22 | 6 | 6 | 6 | scale_bar | ok | 1.3 |
| 23 | 3 | 3 | 3 | scale_bar | ok | 2.0 |
| 24 | 4 | 4 | 4 | scale_bar | ok | 1.8 |
| 25 | 5 | 5 | 5 | scale_bar | ok | 1.6 |
| 26 | 6 | 6 | 6 | scale_bar | ok | 1.5 |
| 27 | 3 | 3 | 3 | scale_bar | ok | 2.1 |
| 28 | 5 | 5 | 5 | scale_bar | ok | 2.1 |
| 29 | 7 | 7 | 7 | scale_bar | ok | 3.1 |