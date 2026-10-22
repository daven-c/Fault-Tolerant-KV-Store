#!/bin/bash
# Re-records docs/demo.{cast,gif,mp4} and docs/demo-final.png from a real run of bench/demo.py.
# Requires: asciinema, agg, ffmpeg (brew install asciinema agg ffmpeg). Run from the repo root.
#
# The run is recorded with asciinema first and rendered afterwards, so recording costs no CPU
# while the cluster is running and the numbers on screen are real.
set -euo pipefail

BIN=${BIN:-bench/.cache/build-worktree-Release/server}
python3 -c "import sys; sys.path.insert(0, 'bench'); from harness import build, find_toolchain; build(None, find_toolchain(None), 'Release')"

asciinema rec --headless --overwrite --window-size 108x48 \
    --title "Fault-Tolerant KV Store live demo" \
    -c "bash -c 'printf \"\$ python3 bench/demo.py\n\"; sleep 1; python3 bench/demo.py --pace 1.2 --bin $BIN; sleep 3'" \
    docs/demo.cast

if ! grep -q "every guarantee held" docs/demo.cast; then
    echo "The recorded run reported a violated guarantee; not rendering it." >&2
    exit 1
fi

agg --theme github-dark --font-size 18 --font-family "JetBrains Mono,Menlo,SF Mono" \
    --idle-time-limit 2 --last-frame-duration 5 docs/demo.cast docs/demo.gif
ffmpeg -v error -y -i docs/demo.gif -movflags +faststart -pix_fmt yuv420p -c:v libx264 -crf 20 \
    -vf "fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2" docs/demo.mp4
ffmpeg -v quiet -y -i docs/demo.gif -fps_mode passthrough -update 1 docs/demo-final.png  # keeps the last frame
echo "Wrote docs/demo.cast, docs/demo.gif, docs/demo.mp4, docs/demo-final.png"
