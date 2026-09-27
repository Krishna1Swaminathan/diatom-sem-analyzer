# Synthetic benchmark (30 frames, crowded)

Random scenes of 7 look-alike species at 35-70 nm/pixel with random damage and noise; the scale is read from the image's own scale bar.

## Detection, scale, measurements

| measure | result |
|---|---|
| Frustules (truth / detected / matched IoU≥0.5) | 150 / 114 / 107 |
| Precision / recall / F1 | 93.9 % / 71.3 % / 81.1 % |
| Mean count error per image | 1.20 |
| Scale correct (±1 %) | 30/30 |
| Length error (mean / 90th pct) | 3.7 % / 4.0 % |
| Width error (mean) | 22.3 % |
| Orientation error (mean / max) | 1.34° / 15.88° |
| Centric vs pennate correct | 92.6 % |
| Pore count error (mean) | 14.4 % |
| Pore diameter bias (mean) | -11 nm |
| Time per image | 2.2 s |

## Damage grading (no species library)

Accuracy: **84.1 %**

| truth \ predicted | intact | cracked | fragmented | uncertain |
|---|---|---|---|---|
| intact | 54 | 1 | 11 | 0 |
| cracked | 0 | 20 | 4 | 0 |
| fragmented | 1 | 0 | 16 | 0 |

| species | damage correct |
|---|---|
| Coscinodiscus-like | 12/15 |
| Cyclotella-like | 18/18 |
| Cymbella-like | 15/17 |
| Navicula-like | 16/17 |
| Pinnularia-like | 12/15 |
| Synedra-like | 5/11 |
| Triceratium-like | 12/14 |

### Species, 3 example(s) per species (all frustules)

Accuracy: **87.9 %** (94/107)

| species | correct | accuracy |
|---|---|---|
| Coscinodiscus-like | 14/15 | 93.3 % |
| Cyclotella-like | 18/18 | 100.0 % |
| Cymbella-like | 13/17 | 76.5 % |
| Navicula-like | 16/17 | 94.1 % |
| Pinnularia-like | 12/15 | 80.0 % |
| Synedra-like | 9/11 | 81.8 % |
| Triceratium-like | 12/14 | 85.7 % |

Most common mistakes: Cymbella-like → Navicula-like (4); Synedra-like → Navicula-like (2); Pinnularia-like → Cymbella-like (1); Pinnularia-like → Navicula-like (1); Triceratium-like → Coscinodiscus-like (1); Navicula-like → Synedra-like (1)

Intact frustules only: 84.8 %. Damage accuracy with this library (species-relative outline tests): 84.1 %.

### Species missing from the library

Leaving each species out of a 3-example library in turn, **51.5 %** of its intact specimens were reported as *unknown* (34/66); the rest were given the closest look-alike's name.

## Per image

| seed | truth | detected | matched | scale source | scale | s |
|---|---|---|---|---|---|---|
| 1000 | 4 | 4 | 4 | scale_bar | ok | 1.3 |
| 1001 | 6 | 4 | 3 | scale_bar | ok | 2.7 |
| 1002 | 6 | 6 | 6 | scale_bar | ok | 1.3 |
| 1003 | 3 | 3 | 3 | scale_bar | ok | 0.7 |
| 1004 | 6 | 5 | 5 | scale_bar | ok | 1.1 |
| 1005 | 5 | 5 | 5 | scale_bar | ok | 2.8 |
| 1006 | 5 | 4 | 4 | scale_bar | ok | 1.2 |
| 1007 | 3 | 3 | 3 | scale_bar | ok | 3.2 |
| 1008 | 4 | 4 | 4 | scale_bar | ok | 1.6 |
| 1009 | 6 | 6 | 6 | scale_bar | ok | 1.0 |
| 1010 | 6 | 2 | 1 | scale_bar | ok | 1.4 |
| 1011 | 4 | 3 | 3 | scale_bar | ok | 0.7 |
| 1012 | 6 | 3 | 2 | scale_bar | ok | 1.3 |
| 1013 | 3 | 2 | 2 | scale_bar | ok | 2.7 |
| 1014 | 5 | 2 | 1 | scale_bar | ok | 4.2 |
| 1015 | 5 | 4 | 4 | scale_bar | ok | 1.2 |
| 1016 | 6 | 3 | 2 | scale_bar | ok | 5.2 |
| 1017 | 7 | 3 | 2 | scale_bar | ok | 2.3 |
| 1018 | 6 | 3 | 2 | scale_bar | ok | 4.4 |
| 1019 | 4 | 4 | 4 | scale_bar | ok | 1.1 |
| 1020 | 5 | 4 | 4 | scale_bar | ok | 3.6 |
| 1021 | 3 | 3 | 3 | scale_bar | ok | 1.0 |
| 1022 | 6 | 5 | 5 | scale_bar | ok | 1.1 |
| 1023 | 3 | 2 | 2 | scale_bar | ok | 1.3 |
| 1024 | 5 | 5 | 5 | scale_bar | ok | 2.9 |
| 1025 | 6 | 4 | 4 | scale_bar | ok | 4.3 |
| 1026 | 6 | 5 | 5 | scale_bar | ok | 3.7 |
| 1027 | 6 | 6 | 6 | scale_bar | ok | 3.3 |
| 1028 | 5 | 3 | 3 | scale_bar | ok | 1.2 |
| 1029 | 5 | 4 | 4 | scale_bar | ok | 1.5 |