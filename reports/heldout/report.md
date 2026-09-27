# Synthetic benchmark (30 frames)

Random scenes of 7 look-alike species at 35-70 nm/pixel with random damage and noise; the scale is read from the image's own scale bar.

## Detection, scale, measurements

| measure | result |
|---|---|
| Frustules (truth / detected / matched IoU≥0.5) | 142 / 142 / 142 |
| Precision / recall / F1 | 100.0 % / 100.0 % / 100.0 % |
| Mean count error per image | 0.00 |
| Scale correct (±1 %) | 30/30 |
| Length error (mean / 90th pct) | 0.8 % / 1.5 % |
| Width error (mean) | 1.6 % |
| Orientation error (mean / max) | 0.02° / 0.36° |
| Centric vs pennate correct | 100.0 % |
| Pore count error (mean) | 1.7 % |
| Pore diameter bias (mean) | +13 nm |
| Time per image | 1.8 s |

## Damage grading (no species library)

Accuracy: **97.2 %**

| truth \ predicted | intact | cracked | fragmented | uncertain |
|---|---|---|---|---|
| intact | 85 | 0 | 0 | 0 |
| cracked | 4 | 28 | 0 | 0 |
| fragmented | 0 | 0 | 25 | 0 |

| species | damage correct |
|---|---|
| Coscinodiscus-like | 18/18 |
| Cyclotella-like | 24/24 |
| Cymbella-like | 24/24 |
| Navicula-like | 22/22 |
| Pinnularia-like | 19/20 |
| Synedra-like | 11/14 |
| Triceratium-like | 20/20 |

### Species, 1 example(s) per species (all frustules)

Accuracy: **93.7 %** (133/142)

| species | correct | accuracy |
|---|---|---|
| Coscinodiscus-like | 18/18 | 100.0 % |
| Cyclotella-like | 24/24 | 100.0 % |
| Cymbella-like | 20/24 | 83.3 % |
| Navicula-like | 20/22 | 90.9 % |
| Pinnularia-like | 20/20 | 100.0 % |
| Synedra-like | 14/14 | 100.0 % |
| Triceratium-like | 17/20 | 85.0 % |

Most common mistakes: Cymbella-like → Navicula-like (4); Triceratium-like → Coscinodiscus-like (2); Triceratium-like → Pinnularia-like (1); Navicula-like → Cymbella-like (1); Navicula-like → Synedra-like (1)

Intact frustules only: 94.1 %. Damage accuracy with this library (species-relative outline tests): 97.2 %.

### Species, 3 example(s) per species (all frustules)

Accuracy: **96.5 %** (137/142)

| species | correct | accuracy |
|---|---|---|
| Coscinodiscus-like | 18/18 | 100.0 % |
| Cyclotella-like | 24/24 | 100.0 % |
| Cymbella-like | 21/24 | 87.5 % |
| Navicula-like | 22/22 | 100.0 % |
| Pinnularia-like | 20/20 | 100.0 % |
| Synedra-like | 14/14 | 100.0 % |
| Triceratium-like | 18/20 | 90.0 % |

Most common mistakes: Cymbella-like → Navicula-like (3); Triceratium-like → Pinnularia-like (1); Triceratium-like → Coscinodiscus-like (1)

Intact frustules only: 96.5 %. Damage accuracy with this library (species-relative outline tests): 97.2 %.

### Species, 5 example(s) per species (all frustules)

Accuracy: **97.9 %** (139/142)

| species | correct | accuracy |
|---|---|---|
| Coscinodiscus-like | 18/18 | 100.0 % |
| Cyclotella-like | 24/24 | 100.0 % |
| Cymbella-like | 24/24 | 100.0 % |
| Navicula-like | 21/22 | 95.5 % |
| Pinnularia-like | 20/20 | 100.0 % |
| Synedra-like | 14/14 | 100.0 % |
| Triceratium-like | 18/20 | 90.0 % |

Most common mistakes: Triceratium-like → Pinnularia-like (1); Triceratium-like → Coscinodiscus-like (1); Navicula-like → Synedra-like (1)

Intact frustules only: 100.0 %. Damage accuracy with this library (species-relative outline tests): 97.2 %.

### Species missing from the library

Leaving each species out of a 5-example library in turn, **63.5 %** of its intact specimens were reported as *unknown* (54/85); the rest were given the closest look-alike's name.

## Per image

| seed | truth | detected | matched | scale source | scale | s |
|---|---|---|---|---|---|---|
| 1000 | 4 | 4 | 4 | scale_bar | ok | 1.4 |
| 1001 | 5 | 5 | 5 | scale_bar | ok | 2.1 |
| 1002 | 6 | 6 | 6 | scale_bar | ok | 1.2 |
| 1003 | 2 | 2 | 2 | scale_bar | ok | 0.6 |
| 1004 | 6 | 6 | 6 | scale_bar | ok | 1.0 |
| 1005 | 5 | 5 | 5 | scale_bar | ok | 2.7 |
| 1006 | 5 | 5 | 5 | scale_bar | ok | 1.1 |
| 1007 | 3 | 3 | 3 | scale_bar | ok | 3.1 |
| 1008 | 4 | 4 | 4 | scale_bar | ok | 1.5 |
| 1009 | 6 | 6 | 6 | scale_bar | ok | 1.0 |
| 1010 | 5 | 5 | 5 | scale_bar | ok | 1.1 |
| 1011 | 4 | 4 | 4 | scale_bar | ok | 0.8 |
| 1012 | 6 | 6 | 6 | scale_bar | ok | 1.4 |
| 1013 | 3 | 3 | 3 | scale_bar | ok | 2.6 |
| 1014 | 4 | 4 | 4 | scale_bar | ok | 3.3 |
| 1015 | 5 | 5 | 5 | scale_bar | ok | 1.1 |
| 1016 | 5 | 5 | 5 | scale_bar | ok | 3.0 |
| 1017 | 7 | 7 | 7 | scale_bar | ok | 1.6 |
| 1018 | 5 | 5 | 5 | scale_bar | ok | 3.2 |
| 1019 | 4 | 4 | 4 | scale_bar | ok | 1.3 |
| 1020 | 4 | 4 | 4 | scale_bar | ok | 2.1 |
| 1021 | 3 | 3 | 3 | scale_bar | ok | 1.1 |
| 1022 | 6 | 6 | 6 | scale_bar | ok | 1.0 |
| 1023 | 4 | 4 | 4 | scale_bar | ok | 1.6 |
| 1024 | 5 | 5 | 5 | scale_bar | ok | 2.5 |
| 1025 | 6 | 6 | 6 | scale_bar | ok | 2.3 |
| 1026 | 5 | 5 | 5 | scale_bar | ok | 3.0 |
| 1027 | 6 | 6 | 6 | scale_bar | ok | 2.6 |
| 1028 | 4 | 4 | 4 | scale_bar | ok | 1.0 |
| 1029 | 5 | 5 | 5 | scale_bar | ok | 1.4 |