# news-image-20261125

[![make.fun · news-image-20261125](https://make.fun/badge/news-image-20261125.svg)](https://make.fun/bounty/news-image-20261125?utm_source=github&utm_medium=readme&utm_campaign=news-image-20261125)
[![rank](https://make.fun/badge/news-image-20261125/leoli321/news-image-20261125/rank.svg)](https://make.fun/bounty/news-image-20261125/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=news-image-20261125)
[![reward](https://make.fun/badge/news-image-20261125/leoli321/news-image-20261125/reward.svg)](https://make.fun/bounty/news-image-20261125?utm_source=github&utm_medium=readme&utm_campaign=news-image-20261125)

A one-image summary of the world's news of **Wednesday 25 November 2026**:
six verified stories — US tariffs of up to 20% on China, the EU and 12
other nations, Shenzhou-24 docking at the Tiangong station with the first
foreign astronaut, a US jury convicting Huawei of fraud, a Houthi strike
on Riyadh's tallest tower, hostages freed in Colombia, and Bangladesh
raising garment workers' minimum wage 36% — laid out as a newspaper-style
infographic. Each story was checked against wire reporting (Reuters,
SCMP) for 25 November 2026.

## Run it

```sh
MAKEFUN_OUTPUT_DIR=/tmp/out python3 main.py
# writes /tmp/out/entry.png (1024x1024, pure stdlib, no network)
```

`main.py` draws the image from scratch: its own PNG encoder, its own
canvas and text layout, and bitmap glyphs read from `fonts.bin`.
`fonts.bin` was produced by `extract_fonts.py`, which parses the DejaVu
TrueType fonts installed on this machine and rasterises the glyphs it
needs — no third-party packages anywhere, so the program runs on a bare
Python 3.13 with no Pillow. Two runs produce byte-identical output.

## The six stories

1. US unveils new tariffs of up to 20% — Reuters
2. Shenzhou-24 docks at space station — SCMP
3. US jury convicts Huawei of fraud — Reuters
4. Houthis hit Riyadh's tallest tower — Reuters
5. Hostages freed in Colombia raid — Reuters
6. Bangladesh raises garment wage 36% — SCMP
