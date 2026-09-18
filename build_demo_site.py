#!/usr/bin/env python3
"""Build the GitHub Pages demo site assets from the 1k test-split eval outputs.

Muxes the already-generated FLACs onto their source clip, one playable mp4 per
(sample x system), and writes docs/data/samples.json, which docs/index.html renders.
Each row on the page is therefore self-contained: its own video with its own audio.

    python tools/build_demo_site.py --out docs

Nothing here runs a model — every audio file already exists under
<eval_root>/<run>/{gen,sep}/audio/. The 10 runs there share one identical set of 82
basenames, so systems are joined by filename alone.

Two things must not change:

  * Audio is never loudness-normalised. How quiet a system goes when the target is
    inactive is the whole point of the demo; normalising would erase it.
  * Source mp4s carry the original mixture on their AAC track. The silent base encode
    drops it with -an; each output then gets exactly one audio track, the system's own.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
EVAL_ROOT = HOME / "new_mmaudio/Foley-Omni/outputs/eval_test"
DATA_ROOT = HOME / "new_mmaudio/Foley-Omni/data/sv2a_features_1k"

# Page order is this order. `kind` drives the styling in index.html:
#   input / gt  — reference rows, set apart from the model rows
#   gen         — video+text -> audio, no access to the mixture
#   sep         — takes the mixture audio as input; a reference upper bound, NOT a
#                 baseline (AGENTS.md §2(a): never rank sep and gen together)
SYSTEMS = [
    dict(key="mixture", label="Mixture", sub="model input", kind="input",
         path="mixture_passthrough_1k/gen/audio"),
    dict(key="gt", label="Target stem", sub="ground truth", kind="gt",
         path="gt_audio_ceiling/gen/audio"),
    dict(key="foley_omni", label="Foley-Omni", sub="baseline, no fine-tuning", kind="gen",
         path="v2st_baseline_1k/gen/audio"),
    dict(key="selva", label="SelVA", sub="baseline, no fine-tuning", kind="gen",
         path="selva_baseline_1k/audio"),
    dict(key="stage1", label="Stage 1 only", sub="separation", kind="sep",
         path="mini_stage1_sep_1k_selva_ema2000/sep/audio"),
    dict(key="stage2", label="Stage 2 only", sub="2k steps, no stage-1 init", kind="gen",
         path="mini_abl_gen_only_1k_selva_ema2000/gen/audio"),
    # The paper's headline configuration: stage 1 at 2k, then stage 2 at 1k. Stage 2 run
    # on to 2k (…_ema2000) is the weaker row of the same sweep — don't swap it back in.
    dict(key="ours", label="Ours", sub="stage 1 2k → stage 2 1k", kind="gen", highlight=True,
         path="mini_stage2_gen_1k_selva_ema1000/gen/audio"),
]

# 5 clips x 2 stems. Chosen for role variety (onset / span / ambience) so the page
# shows both transient targets and continuous ones. fb_521 is required.
DEFAULT_IDS = [
    "fb_521_stem_01", "fb_521_stem_02",              # golf impact / outdoor ambience
    "fb_01205_stem_01", "fb_01205_stem_02",          # grill fire / tongs on the grill
    "fb_2892_stem_01", "fb_2892_stem_02",            # leaves rustling / metal detector
    "fb_2653_stem_01", "fb_2653_stem_02_attempt02",  # stadium crowd / ball kicks
    "fb_00753_stem_01", "fb_00753_stem_02",          # electromagnet buzz / phone ringing
]

# Per-clip annotation roles live in whichever run has been scored; the roles come from
# the annotation, so any one of them is authoritative.
ONSET_METRICS = "v2st_baseline_1k/gen/metrics_onset_test.json"

# What the badge says. onset and span are both targets with silences to keep, and the page
# draws no distinction between them; ambience sounds throughout and is the one case where
# there is nothing to stay quiet about.
ROLE_LABEL = {"onset": "onset or span", "span": "onset or span", "ambience": "ambience"}



def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"ffmpeg failed:\n  {' '.join(map(str, cmd))}\n{p.stderr[-2000:]}")


def load_manifest(data_root: Path) -> dict:
    out = {}
    with open(data_root / "manifest.jsonl") as f:
        for line in f:
            d = json.loads(line)
            if d.get("split") != "test":
                continue
            prompt = (d["prompt"]
                      .replace("[AUDIO_CAPTION]", "")
                      .replace("[END_AUDIO_CAPTION]", "")
                      .strip())
            out[d["id"]] = dict(group_id=d["group_id"], prompt=prompt)
    return out


def load_roles(eval_root: Path) -> dict:
    path = eval_root / ONSET_METRICS
    if not path.exists():
        print(f"note: {path} missing — role badges will be omitted", file=sys.stderr)
        return {}
    payload = json.load(open(path))
    return {e["id"]: dict(role=e.get("role"), duration=e.get("duration"))
            for e in payload.get("per_clip", [])}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eval_root", type=Path, default=EVAL_ROOT)
    ap.add_argument("--data_root", type=Path, default=DATA_ROOT)
    ap.add_argument("--out", type=Path, default=Path("."))
    ap.add_argument("--ids", nargs="+", default=DEFAULT_IDS,
                    help="sample ids to publish (default: the 10 curated stems)")
    ap.add_argument("--audio_bitrate", default="96k")
    ap.add_argument("--video_height", type=int, default=270)
    ap.add_argument("--video_crf", default="30")
    ap.add_argument("--cache_dir", type=Path, default=Path(".demo_build"),
                    help="where the silent per-clip base encodes are kept between builds")
    ap.add_argument("--force", action="store_true", help="re-encode files that exist")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found on PATH")
    if not args.eval_root.is_dir():
        sys.exit(f"eval_root not found: {args.eval_root}")

    manifest = load_manifest(args.data_root)
    roles = load_roles(args.eval_root)

    # Resolve every source up front so a missing file fails the build instead of
    # silently dropping a column.
    missing = []
    for sid in args.ids:
        if sid not in manifest:
            missing.append(f"{sid}: not in manifest (test split)")
        for sysd in SYSTEMS:
            src = args.eval_root / sysd["path"] / f"{sid}.flac"
            if not src.exists():
                missing.append(f"{sid}: {sysd['key']} -> {src}")
        vid = args.data_root / "test_gt_video" / f"{sid}.mp4"
        if not vid.exists():
            missing.append(f"{sid}: video -> {vid}")
    if missing:
        sys.exit("missing sources:\n  " + "\n  ".join(missing))

    clips_dir = args.out / "media/clips"
    base_dir = args.cache_dir / "video"
    (args.out / "data").mkdir(parents=True, exist_ok=True)
    base_dir.mkdir(parents=True, exist_ok=True)

    n_enc = 0
    samples = []
    base_of = {}

    for sid in args.ids:
        meta = manifest[sid]
        clip = meta["group_id"]

        # Silent base encode, once per clip — both stems of a group share one source mp4.
        # It is a build artefact, not part of the site: every published file has audio.
        base = base_dir / f"{clip}.mp4"
        if clip not in base_of:
            base_of[clip] = base
            if args.force or not base.exists():
                src_video = (args.data_root / "test_gt_video" / f"{sid}.mp4").resolve()
                run(["ffmpeg", "-y", "-i", str(src_video),
                     "-an",                                   # drop the mixture track
                     "-vf", f"scale=-2:{args.video_height}",
                     "-c:v", "libx264", "-crf", args.video_crf, "-preset", "slow",
                     "-pix_fmt", "yuv420p", str(base)])
                n_enc += 1

        clips = {}
        for sysd in SYSTEMS:
            dst_dir = clips_dir / sysd["key"]
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / f"{sid}.mp4"
            if args.force or not dst.exists():
                src = args.eval_root / sysd["path"] / f"{sid}.flac"
                # -c:v copy: the base encode is reused verbatim across all seven systems.
                # No audio filters: any gain change would flatten the level differences
                # between systems, which is what the page is here to demonstrate.
                # -shortest trims the flac's silent tail back to the length of the clip.
                run(["ffmpeg", "-y", "-i", str(base), "-i", str(src),
                     "-map", "0:v:0", "-map", "1:a:0",
                     "-c:v", "copy", "-c:a", "aac", "-b:a", args.audio_bitrate,
                     "-shortest", "-movflags", "+faststart", str(dst)])
                n_enc += 1
            clips[sysd["key"]] = str(dst.relative_to(args.out))

        r = roles.get(sid, {})
        samples.append(dict(
            id=sid,
            clip=clip,
            prompt=meta["prompt"],
            role=ROLE_LABEL.get(r.get("role"), r.get("role")),
            duration=r.get("duration"),
            clips=clips,
        ))

    payload = dict(
        systems=[{k: v for k, v in s.items() if k != "path"} for s in SYSTEMS],
        samples=samples,
    )
    out_json = args.out / "data/samples.json"
    with open(out_json, "w") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False)
        f.write("\n")

    # index.html loads this one with a <script> tag rather than fetch(), so the page
    # also opens straight off the filesystem without a server.
    out_js = args.out / "data/samples.js"
    with open(out_js, "w") as f:
        f.write("window.DEMO_DATA = ")
        json.dump(payload, f, indent=1, ensure_ascii=False)
        f.write(";\n")

    media = sorted(p for p in (args.out / "media").rglob("*") if p.is_file())
    total = sum(p.stat().st_size for p in media)
    print(f"{len(samples)} samples · {len(SYSTEMS)} systems · {len(base_of)} clips")
    print(f"{len(media)} published files, {total / 1e6:.1f} MB ({n_enc} ffmpeg runs)")
    print(f"wrote {out_json} and {out_js}")


if __name__ == "__main__":
    main()
