// Demo recorder template (from the make-demo skill). Copy into the project, then edit CONFIG,
// warmUp() and STEPS. One run produces:
//   <outDir>/demo.webm             video for the MP4/GIF (encode with encode.sh)
//   <outDir>/tour/steps.json + *.jpg   screenshots + hotspots for the interactive tour (build_tour.mjs)
//
//   DEMO_URL=http://localhost:5173 node scripts/record-demo.mjs
//
// Requires `playwright` (dev dependency). Uses the installed Google Chrome because Playwright's
// bundled Chromium can't decode H.264/AAC; set DEMO_CHANNEL="" to use bundled Chromium instead.

import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { mkdir, readdir, rename, rm, writeFile } from "node:fs/promises";
import path from "node:path";

const CONFIG = {
	// With no DEMO_URL the recorder starts its own dashboard (fresh cluster, clean event log).
	url: process.env.DEMO_URL ?? "http://localhost:8097",
	serverBin: process.env.DEMO_SERVER_BIN, // optional prebuilt server; otherwise the dashboard builds it
	outDir: path.resolve(process.env.DEMO_OUT ?? "demo-out"),
	size: { width: 1280, height: 800 },
	colorScheme: "dark",
	channel: process.env.DEMO_CHANNEL ?? "chrome",
	typeDelayMs: 55,
};

// Start from a fresh 5-node cluster with no load (rebuilding it only if it has been used, so the
// event log stays clean), and wait until it has elected a leader.
let dashboard = null;
async function startDashboard() {
	if (process.env.DEMO_URL) return;
	const repo = path.resolve(import.meta.dirname, "../..");
	const args = ["dashboard/server.py", "--no-browser", "--port", new URL(CONFIG.url).port, "--base-port", "20500"];
	if (CONFIG.serverBin) args.push("--bin", path.resolve(CONFIG.serverBin));
	dashboard = spawn("python3", args, { cwd: repo, stdio: "ignore" });
	for (let i = 0; i < 600; i++) {
		try { await fetch(`${CONFIG.url}/api/state`); return; } catch { await sleep(200); }
	}
	throw new Error("dashboard didn't start");
}

async function warmUp() {
	await startDashboard();
	const post = (p, body) =>
		fetch(`${CONFIG.url}/api/${p}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
	const s0 = await (await fetch(`${CONFIG.url}/api/state`)).json();
	const fresh = s0.size === 5 && s0.load.clients === 0 && s0.events.length <= 2 &&
		s0.nodes.every((n) => ["leader", "follower", "candidate"].includes(n.status));
	if (!fresh) {
		if (s0.load.clients) await post("load", { clients: 0 });
		await post("cluster", { size: 5 });
	}
	for (let i = 0; i < 100; i++) {
		const s = await (await fetch(`${CONFIG.url}/api/state`)).json();
		if (s.nodes.some((n) => n.status === "leader")) return;
		await sleep(100);
	}
	throw new Error("no leader elected");
}

// --- dashboard helpers (read the page's own state, so waits follow the UI) ---
const leaderId = (page) => page.evaluate(() => snap?.nodes.find((n) => n.status === "leader")?.id ?? null);
const statusOf = (page, i) => page.evaluate((i) => snap?.nodes[i]?.status, i);
const node = (page, i) => page.locator("#map .node").nth(i);
const action = (page, name) => page.locator(`#inspector [data-act="${name}"]`);
async function selectNode({ page, click }, i, note) {
	if ((await page.evaluate(() => selected)) !== i) await click(node(page, i), note);
	await page.locator("#inspector h3", { hasText: `Node ${i}` }).waitFor();
}
async function waitFor(page, fn, arg, timeout = 15000) {
	await page.waitForFunction(fn, arg, { timeout, polling: 100 });
}
async function send({ page, type, glide }, line, target = "") {
	const select = page.locator("#target");
	if ((await select.inputValue()) !== target) {
		await glide(select);
		await select.selectOption(target);
		await sleep(400);
	}
	const before = await page.locator("#history .entry").count();
	await type(page.locator("#cmd"), line);
	await sleep(250);
	await page.keyboard.press("Enter");
	// wait until the new entry has its reply
	await waitFor(page, (n) => {
		const e = document.querySelectorAll("#history .entry")[n];
		return e && !e.querySelector("pre").textContent.startsWith("…");
	}, before, 20000);
}

const STEPS = [
	{
		caption: "A real 5-node Raft cluster on localhost. One node won the election and leads.",
		run: async ({ page, wait, snap }) => {
			await waitFor(page, () => snap?.nodes?.some((n) => n.status === "leader"));
			await wait(3500);
			await snap("Five server processes; the blue node won the election and is the leader.");
		},
	},
	{
		caption: "Send a command: the dashboard routes it to the leader",
		run: async (h) => {
			await send(h, "SET city Lisbon");
			await h.wait(2200);
			await h.snap("SET is committed by a majority and acknowledged by the leader.");
		},
	},
	{
		caption: "Ask a follower directly and it redirects you to the leader",
		run: async (h) => {
			const leader = await leaderId(h.page);
			const follower = (leader + 1) % 5;
			await send(h, "GET city", String(follower));
			await h.wait(2600);
			await h.snap("Followers don't serve commands; they reply NOT_LEADER with the leader's address.");
		},
	},
	{
		caption: "Start 32 concurrent clients",
		run: async ({ page, glide, wait, snap }) => {
			const slider = page.locator("#load");
			const box = await glide(slider);
			const y = box.y + box.height / 2;
			await page.mouse.move(box.x + 8, y, { steps: 8 });
			await page.mouse.down();
			await page.mouse.move(box.x + 8 + (box.width - 16) * 0.5, y, { steps: 30 });
			await page.mouse.up();
			const termBefore = await page.evaluate(() => Math.max(...snap.nodes.map((n) => n.term || 0)));
			await waitFor(page, () => (snap?.load?.series?.at(-1)?.ops ?? 0) > 500);
			await wait(3500);
			// Nothing has failed yet, so an election here would make the next captions misleading.
			const termAfter = await page.evaluate(() => Math.max(...snap.nodes.map((n) => n.term || 0)));
			if (termAfter !== termBefore) throw new Error("an election happened while load started; re-record");
			await snap("Thousands of SET/GET requests per second flow through the leader to every follower.");
		},
	},
	{
		caption: "Kill the leader while it's under load",
		run: async (h) => {
			const { page, click, wait } = h;
			const leader = await leaderId(page);
			await selectNode(h, leader, "Select the leader");
			await wait(900);
			await click(action(page, "kill"), "Kill it with SIGKILL");
			await h.caption("The followers time out and elect a new leader");
			await waitFor(page, (old) => {
				const l = snap?.nodes.find((n) => n.status === "leader");
				return l && l.id !== old;
			}, leader);
			await wait(4500);
			await h.snap("A new leader is elected and the load generator carries on against it.");
		},
	},
	{
		caption: "Pause a follower: it freezes, and the rest of the cluster carries on",
		run: async (h) => {
			const { page, click, wait } = h;
			const leader = await leaderId(page);
			const follower = await page.evaluate(() => snap.nodes.find((n) => n.status === "follower").id);
			await selectNode(h, follower, "Select a follower");
			await wait(700);
			await click(action(page, "pause"), "Pause it (SIGSTOP): a hung server");
			await waitFor(page, (i) => snap?.nodes[i]?.status === "paused", follower);
			await wait(3000);
			const termBefore = await page.evaluate(() => Math.max(...snap.nodes.map((n) => n.term || 0)));
			await click(action(page, "resume"), "Resume it");
			await waitFor(page, (i) => snap?.nodes[i]?.status === "follower", follower);
			await wait(600);
			// Caption what actually happened: a resumed node often calls an election (no PreVote yet).
			const termAfter = await page.evaluate(() => Math.max(...snap.nodes.map((n) => n.term || 0)));
			await h.caption(termAfter > termBefore
				? "On resume it called an election and bumped the term: a known Raft quirk that PreVote prevents"
				: "Resumed, it catches up and rejoins as a follower");
			await wait(3200);
		},
	},
	{
		caption: "Kill two more nodes: 2 of 5 left, no majority",
		run: async (h) => {
			const { page, click, wait } = h;
			const leader = await leaderId(page);
			const victims = await page.evaluate((l) => snap.nodes.filter((n) => n.status === "follower" && n.id !== l).map((n) => n.id).slice(0, 2), leader);
			for (const v of victims) {
				await selectNode(h, v, `Select node ${v}`);
				await wait(500);
				await click(action(page, "kill"), `Kill node ${v}`);
				await waitFor(page, (i) => snap?.nodes[i]?.status === "down", v);
				await wait(700);
			}
			await h.caption("Without a majority the leader can't acknowledge writes");
			await send(h, "SET status outage", "");
			await wait(2500);
			await h.snap("With 2 of 5 nodes up the write is not acknowledged: it can't be made durable yet.");
		},
	},
	{
		caption: "Restart the dead nodes: quorum returns and they catch up from their saved logs",
		run: async (h) => {
			const { page, click, wait } = h;
			const down = await page.evaluate(() => snap.nodes.filter((n) => n.status === "down").map((n) => n.id));
			for (const d of down) {
				await selectNode(h, d, `Select node ${d}`);
				await wait(400);
				await click(action(page, "restart"), `Start node ${d} again: it reloads its saved Raft log`);
				await waitFor(page, (i) => snap?.nodes[i]?.status !== "down", d);
				await wait(500);
			}
			await waitFor(page, () => snap?.nodes.every((n) => ["leader", "follower"].includes(n.status)), null, 20000);
			await wait(3500);
			await h.snap("All five nodes are back; the restarted ones replay the entries they missed.");
		},
	},
	{
		caption: "Read back the first write",
		run: async (h) => {
			const sel = await h.page.evaluate(() => selected);
			if (sel != null) await h.click(node(h.page, sel), false); // deselect: give the console room
			await h.page.locator("#inspector .empty").waitFor();
			await send(h, "GET city", "");
			const reply = await h.page.locator("#history .entry pre").last().textContent();
			if (reply.trim() !== '"Lisbon"') throw new Error(`final read returned ${reply}; not captioning it as survived`);
			await h.caption("The first write survived the leader crash, the pause and the outage");
			await h.wait(2500);
			await h.snap("The value written at the start survived the leader crash, the pause and the outage.");
			await h.caption("Try it yourself: python3 dashboard/server.py");
			await h.wait(3000);
		},
	},
];

// ---------------------------------------------------------------------------------------------

const overlay = () => {
	const style = document.createElement("style");
	style.textContent = `
		#demo-cursor { position: fixed; z-index: 2147483647; width: 18px; height: 18px; margin: -9px 0 0 -9px;
			border-radius: 50%; background: rgba(255,255,255,.85); box-shadow: 0 0 0 2px rgba(20,184,166,.9);
			pointer-events: none; transition: transform .12s; left: -50px; top: -50px; }
		#demo-cursor.down { transform: scale(.7); }
		#demo-caption { position: fixed; z-index: 2147483646; left: 50%; bottom: 28px; transform: translateX(-50%);
			max-width: 80%; padding: 10px 18px; border-radius: 10px; background: rgba(15,23,42,.88); color: #fff;
			font: 500 17px/1.35 system-ui, sans-serif; text-align: center; opacity: 0; transition: opacity .3s;
			pointer-events: none; }
		.demo-hide #demo-cursor, .demo-hide #demo-caption { visibility: hidden !important; }`;
	const cursor = Object.assign(document.createElement("div"), { id: "demo-cursor" });
	const caption = Object.assign(document.createElement("div"), { id: "demo-caption" });
	const mount = () => document.body.append(style, cursor, caption);
	document.body ? mount() : addEventListener("DOMContentLoaded", mount);
	addEventListener("mousemove", (e) => { cursor.style.left = `${e.clientX}px`; cursor.style.top = `${e.clientY}px`; }, true);
	addEventListener("mousedown", () => cursor.classList.add("down"), true);
	addEventListener("mouseup", () => cursor.classList.remove("down"), true);
	window.__caption = (text) => {
		caption.textContent = text ?? "";
		caption.style.opacity = text ? "1" : "0";
	};
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
	const tourDir = path.join(CONFIG.outDir, "tour");
	await rm(tourDir, { recursive: true, force: true });
	await mkdir(tourDir, { recursive: true });
	await warmUp();

	const browser = await chromium.launch({
		...(CONFIG.channel ? { channel: CONFIG.channel } : {}),
		args: ["--autoplay-policy=no-user-gesture-required"],
	});
	const context = await browser.newContext({
		viewport: CONFIG.size,
		colorScheme: CONFIG.colorScheme,
		recordVideo: { dir: CONFIG.outDir, size: CONFIG.size },
	});
	await context.addInitScript(overlay);
	const recordingStarted = performance.now(); // video capture starts with the page
	const page = await context.newPage();
	const video = page.video();
	let readyAt = 0;

	const tour = [];
	let currentCaption = "";

	// Tour screenshots hide the fake cursor and caption; the tour draws its own hotspot and text.
	async function snap(note, box = null) {
		const file = `step-${String(tour.length + 1).padStart(2, "0")}.jpg`;
		await page.evaluate(() => document.documentElement.classList.add("demo-hide"));
		await page.screenshot({ path: path.join(tourDir, file), type: "jpeg", quality: 80 });
		await page.evaluate(() => document.documentElement.classList.remove("demo-hide"));
		tour.push({
			image: file,
			caption: note ?? currentCaption,
			hotspot: box && {
				x: box.x / CONFIG.size.width,
				y: box.y / CONFIG.size.height,
				w: box.width / CONFIG.size.width,
				h: box.height / CONFIG.size.height,
			},
		});
	}

	async function glide(locator) {
		await locator.scrollIntoViewIfNeeded();
		const box = await locator.boundingBox();
		if (!box) throw new Error("glide: element not visible");
		await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 25 });
		return box;
	}

	// Real mouse click at the element's centre: overlays on top of the target receive it and
	// bubble it, exactly like a user's click. (locator.click() refuses when something covers it.)
	async function click(locator, note) {
		const box = await glide(locator);
		if (note !== false) await snap(note, box);
		await sleep(250);
		await page.mouse.down();
		await sleep(80);
		await page.mouse.up();
	}

	async function type(locator, text) {
		await click(locator, false);
		await locator.fill("");
		await locator.pressSequentially(text, { delay: CONFIG.typeDelayMs });
	}

	async function caption(text) {
		currentCaption = text ?? "";
		await page.evaluate((t) => window.__caption(t), text);
	}

	const helpers = { page, click, type, snap, caption, glide, wait: sleep };

	try {
		await page.goto(CONFIG.url);
		// "load", not "networkidle": apps with polling/streaming requests never go idle
		await page.waitForLoadState("load");
		await sleep(500); // let the first paint settle; steps should still wait on their own UI state
		// everything before this is a blank/white page load; encode.sh trims it using recording.json
		readyAt = (performance.now() - recordingStarted) / 1000;
		await page.mouse.move(CONFIG.size.width / 2, CONFIG.size.height * 0.7);
		for (const step of STEPS) {
			if (step.caption !== undefined) await caption(step.caption);
			await step.run(helpers);
		}
		await caption(null);
		await sleep(500);
	} finally {
		await context.close();
		await browser.close();
		dashboard?.kill("SIGTERM");
	}

	const out = path.join(CONFIG.outDir, "demo.webm");
	await rm(out, { force: true });
	await rename(await video.path(), out);
	await writeFile(
		path.join(tourDir, "steps.json"),
		JSON.stringify({ size: CONFIG.size, steps: tour }, null, 2) + "\n"
	);
	await writeFile(
		path.join(CONFIG.outDir, "recording.json"),
		JSON.stringify({ readyAt: Number(readyAt.toFixed(2)) }) + "\n"
	);
	console.log(`recorded ${out} (app ready at ${readyAt.toFixed(1)}s)\ntour: ${tour.length} steps in ${tourDir}`);
}

main().catch(async (e) => {
	console.error(e);
	dashboard?.kill("SIGTERM");
	// drop partial recordings (page@<hash>.webm) left by a failed run
	for (const f of await readdir(CONFIG.outDir).catch(() => [])) {
		if (/^page@.*\.webm$/.test(f)) await rm(path.join(CONFIG.outDir, f), { force: true });
	}
	process.exit(1);
});
