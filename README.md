# Keep the Silences — demo page

Audio samples for *Keep the Silences: Source Isolation for Selective Video-to-Audio
Generation*. Static site, served by GitHub Pages from the repository root. Nothing here is hand-edited except
`index.html` — every file under `media/` and `data/` is generated.

Each published file is one playable clip: the sample's video with one system's audio muxed
onto it (`media/clips/<system>/<id>.mp4`), so a tile on the page needs no JavaScript sync.
The silent per-clip base encodes are build artefacts, kept in `.demo_build/` (gitignored)
and reused across all seven systems with `-c:v copy`.

## Rebuild

```bash
python build_demo_site.py --out .          # build only what is missing
python build_demo_site.py --out . --force  # rebuild everything
```

Swap the samples without touching the page:

```bash
python build_demo_site.py --out . --ids fb_521_stem_01 fb_521_stem_02 fb_3071_stem_01 ...
```

Sources are read from `~/new_mmaudio/Foley-Omni/outputs/eval_test` and
`~/new_mmaudio/Foley-Omni/data/sv2a_features_1k` (override with `--eval_root` / `--data_root`).
A missing source aborts the build rather than dropping a column.

## Preview

```bash
python3 -m http.server 8080
```

`index.html` loads its data through `data/samples.js`, so opening the file directly also works.
Roughly 22 MB of media, 70 clips.

## Publish

GitHub → Settings → Pages → Source: *Deploy from a branch*, Branch: `main`, folder `/ (root)`.

## Which checkpoint is "Ours"

`mini_stage2_gen_1k_selva_ema1000` — stage 1 at 2k steps, then stage 2 at 1k. That is the
configuration the paper reports (the 17.5 dB row of Table 1 / §5.3), not `…_ema2000`, which is
the weaker 2k+2k row of the same sweep.

## No numbers on the page

The demo is listening only — there is no metrics table, and the sample notes name no metric.
The audio comes from the new-server retrain (2026-09-09 – 09-11), whose numbers differ from
`PAPER_PLAN.md` §2 and `results/eval_test/` (old server); keeping figures off the page avoids
putting one server's numbers next to the other's audio.
