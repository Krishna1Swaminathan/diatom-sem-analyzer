# Synthetic benchmark (30 frames, crowded)

Random scenes of 7 look-alike species at 35-70 nm/pixel with random damage and noise; the scale is read from the image's own scale bar.

## Detection, scale, measurements

| measure | result |
|---|---|
| Frustules (truth / detected / matched IoU≥0.5) | 133 / 114 / 111 |
| Precision / recall / F1 | 97.4 % / 83.5 % / 89.9 % |
| Mean count error per image | 0.63 |
| Scale correct (±1 %) | 30/30 |
| Length error (mean / 90th pct) | 4.0 % / 4.4 % |
| Width error (mean) | 12.2 % |
| Orientation error (mean / max) | 1.16° / 8.56° |
| Centric vs pennate correct | 92.1 % |
| Pore count error (mean) | 15.1 % |
| Pore diameter bias (mean) | -8 nm |
| Time per image | 1.6 s |

## Damage grading (no species library)

Accuracy: **82.0 %**

| truth \ predicted | intact | cracked | fragmented | uncertain |
|---|---|---|---|---|
| intact | 59 | 1 | 14 | 0 |
| cracked | 0 | 16 | 3 | 0 |
| fragmented | 1 | 1 | 16 | 0 |

| species | damage correct |
|---|---|
| Coscinodiscus-like | 16/22 |
| Cyclotella-like | 18/20 |
| Cymbella-like | 17/19 |
| Navicula-like | 10/11 |
| Pinnularia-like | 8/13 |
| Synedra-like | 4/6 |
| Triceratium-like | 18/20 |

### Species, 1 example(s) per species (all frustules)

Accuracy: **85.6 %** (95/111)

| species | correct | accuracy |
|---|---|---|
| Coscinodiscus-like | 16/22 | 72.7 % |
| Cyclotella-like | 19/20 | 95.0 % |
| Cymbella-like | 17/19 | 89.5 % |
| Navicula-like | 10/11 | 90.9 % |
| Pinnularia-like | 10/13 | 76.9 % |
| Synedra-like | 5/6 | 83.3 % |
| Triceratium-like | 18/20 | 90.0 % |

Most common mistakes: Pinnularia-like → Navicula-like (3); Coscinodiscus-like → Pinnularia-like (2); Cymbella-like → Navicula-like (2); Coscinodiscus-like → Cyclotella-like (2); Triceratium-like → unknown (1); Navicula-like → Cymbella-like (1)

Intact frustules only: 85.1 %. Damage accuracy with this library (species-relative outline tests): 82.0 %.

### Species, 3 example(s) per species (all frustules)

Accuracy: **87.4 %** (97/111)

| species | correct | accuracy |
|---|---|---|
| Coscinodiscus-like | 18/22 | 81.8 % |
| Cyclotella-like | 19/20 | 95.0 % |
| Cymbella-like | 18/19 | 94.7 % |
| Navicula-like | 11/11 | 100.0 % |
| Pinnularia-like | 10/13 | 76.9 % |
| Synedra-like | 5/6 | 83.3 % |
| Triceratium-like | 16/20 | 80.0 % |

Most common mistakes: Pinnularia-like → Navicula-like (3); Triceratium-like → unknown (2); Coscinodiscus-like → Cymbella-like (2); Triceratium-like → Cymbella-like (1); Cyclotella-like → unknown (1); Coscinodiscus-like → Navicula-like (1)

Intact frustules only: 85.1 %. Damage accuracy with this library (species-relative outline tests): 82.0 %.

### Species, 5 example(s) per species (all frustules)

Accuracy: **87.4 %** (97/111)

| species | correct | accuracy |
|---|---|---|
| Coscinodiscus-like | 18/22 | 81.8 % |
| Cyclotella-like | 19/20 | 95.0 % |
| Cymbella-like | 18/19 | 94.7 % |
| Navicula-like | 10/11 | 90.9 % |
| Pinnularia-like | 10/13 | 76.9 % |
| Synedra-like | 5/6 | 83.3 % |
| Triceratium-like | 17/20 | 85.0 % |

Most common mistakes: Triceratium-like → unknown (3); Pinnularia-like → Navicula-like (3); Coscinodiscus-like → Cymbella-like (2); Navicula-like → Cymbella-like (1); Cyclotella-like → unknown (1); Coscinodiscus-like → Navicula-like (1)

Intact frustules only: 83.8 %. Damage accuracy with this library (species-relative outline tests): 82.0 %.

### Species missing from the library

Leaving each species out of a 5-example library in turn, **67.6 %** of its intact specimens were reported as *unknown* (50/74); the rest were given the closest look-alike's name.

## Per image

| seed | truth | detected | matched | scale source | scale | s |
|---|---|---|---|---|---|---|
| 100 | 6 | 6 | 6 | scale_bar | ok | 2.5 |
| 101 | 4 | 2 | 1 | scale_bar | ok | 1.2 |
| 102 | 4 | 4 | 4 | scale_bar | ok | 1.3 |
| 103 | 5 | 5 | 5 | scale_bar | ok | 2.2 |
| 104 | 5 | 4 | 4 | scale_bar | ok | 1.2 |
| 105 | 4 | 2 | 1 | scale_bar | ok | 4.5 |
| 106 | 5 | 5 | 5 | scale_bar | ok | 2.0 |
| 107 | 3 | 3 | 3 | scale_bar | ok | 0.9 |
| 108 | 3 | 3 | 3 | scale_bar | ok | 1.1 |
| 109 | 5 | 4 | 4 | scale_bar | ok | 1.4 |
| 110 | 5 | 4 | 4 | scale_bar | ok | 1.2 |
| 111 | 5 | 5 | 5 | scale_bar | ok | 1.0 |
| 112 | 3 | 2 | 2 | scale_bar | ok | 1.5 |
| 113 | 4 | 4 | 4 | scale_bar | ok | 3.5 |
| 114 | 3 | 3 | 3 | scale_bar | ok | 0.9 |
| 115 | 6 | 3 | 3 | scale_bar | ok | 1.2 |
| 116 | 4 | 4 | 4 | scale_bar | ok | 1.6 |
| 117 | 3 | 3 | 3 | scale_bar | ok | 1.2 |
| 118 | 4 | 4 | 4 | scale_bar | ok | 1.9 |
| 119 | 5 | 4 | 4 | scale_bar | ok | 1.4 |
| 120 | 4 | 3 | 3 | scale_bar | ok | 1.6 |
| 121 | 4 | 3 | 2 | scale_bar | ok | 2.0 |
| 122 | 6 | 5 | 5 | scale_bar | ok | 1.7 |
| 123 | 3 | 2 | 2 | scale_bar | ok | 1.2 |
| 124 | 7 | 6 | 6 | scale_bar | ok | 2.1 |
| 125 | 5 | 5 | 5 | scale_bar | ok | 1.3 |
| 126 | 4 | 4 | 4 | scale_bar | ok | 1.4 |
| 127 | 5 | 4 | 4 | scale_bar | ok | 1.2 |
| 128 | 5 | 4 | 4 | scale_bar | ok | 1.7 |
| 129 | 4 | 4 | 4 | scale_bar | ok | 0.9 |