# How the demo is recorded

The GIF at the top of the README, `docs/demo.mp4` and the click-through tour (`docs/tour.html`) all
come from one scripted session with the interactive dashboard against a real 5-node cluster on
localhost. Nothing is mocked or edited: every number on screen is what the cluster reported at that
moment. All data is synthetic (keys like `city`, plus the load generator's `load:*` keys).

## The script

[`demo-recorder/record-demo.mjs`](demo-recorder/record-demo.mjs) starts its own dashboard backend
(`dashboard/server.py`, fresh cluster), opens it in Google Chrome through Playwright, and drives it
with real mouse clicks, typing and a slider drag:

1. A 5-node cluster elects a leader.
2. `SET city Lisbon` is routed to the leader; `GET city` sent straight to a follower returns `NOT_LEADER`.
3. 32 concurrent clients start.
4. The leader is killed (`SIGKILL`) under load and the followers elect a new one.
5. A follower is paused (`SIGSTOP`) and resumed.
6. Two more nodes are killed, leaving 2 of 5: a write is not acknowledged.
7. The dead nodes restart, reload their Raft logs and catch up.
8. `GET city` still returns `"Lisbon"`.

The script checks its own claims and aborts rather than record something misleading:

- the final read must return `"Lisbon"`, or the run fails;
- if an election happens while load is starting (nothing has failed yet), the run fails;
- the caption after resuming the paused node says whether it rejoined quietly or called an
  election, based on whether the term changed.

## Re-recording

Requirements: Node 22+, Google Chrome, Python 3.9+, `ffmpeg`, and the server's build dependencies.

```bash
cd docs/demo-recorder
npm install                                    # Playwright, pinned in package.json
node record-demo.mjs                           # -> demo-out/demo.webm + demo-out/tour/
# optional: DEMO_SERVER_BIN=../../bench/.cache/build-worktree-Release/server to skip the build

# encode (from the make-demo toolkit): trims the page-load frames, writes MP4 + GIF
FPS=8 bash encode.sh demo-out/demo.webm ..     # -> docs/demo.mp4, docs/demo.gif (800 px, 8 fps)
node build_tour.mjs demo-out/tour ../tour.html --title "Raft cluster dashboard tour"
```

`encode.sh` and `build_tour.mjs` are general-purpose helpers that aren't vendored here: any H.264
encode of `demo.webm` works (for example
`ffmpeg -i demo-out/demo.webm -c:v libx264 -crf 26 -pix_fmt yuv420p -movflags +faststart demo.mp4`).

Check the result frame by frame before publishing; that is how the issues fixed while making
this demo were found (a hidden console reply, a caption that would have been false, and elections
under load that the script now refuses to record).

The earlier terminal recording (`terminal-demo.*`) is made by
[`record-terminal-demo.sh`](record-terminal-demo.sh) from `bench/demo.py`.
